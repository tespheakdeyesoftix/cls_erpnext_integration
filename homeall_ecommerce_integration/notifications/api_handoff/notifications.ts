// Copy to homeall-ecommerce-api/src/services/frappe/notifications.ts.
// Add the two settings to RuntimeConfig/EnvSchema as described in README.md.
import { z } from 'zod';
import type { RuntimeConfig } from '../../config/env';
import type { Repository } from '../supabase/repository';

const jobsSchema = z.array(z.object({
  id: z.uuid(), claim_id: z.uuid(), attempts: z.number().int(),
  event: z.object({ id: z.uuid(), type: z.enum(['order_created', 'chat_message']),
    created_at: z.string(), payload: z.record(z.string(), z.unknown()) }),
}));

export async function signNotification(secret: string, timestamp: string, body: string) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${timestamp}.${body}`));
  return Array.from(new Uint8Array(signature), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function processFrappeNotifications(config: RuntimeConfig, repository: Repository) {
  const url = config.FRAPPE_NOTIFICATION_WEBHOOK_URL;
  const secret = config.FRAPPE_NOTIFICATION_WEBHOOK_SECRET;
  if (!url || !secret) return;
  const jobs = await repository.rpc('api_claim_frappe_notifications', { p_limit: 25 }, jobsSchema);
  await Promise.all(jobs.map(async (job) => {
    let success = false;
    let error = 'WEBHOOK_UNAVAILABLE';
    try {
      const body = JSON.stringify(job.event);
      const timestamp = String(Math.floor(Date.now() / 1000));
      const signature = await signNotification(secret, timestamp, body);
      const response = await fetch(url, {
        method: 'POST', redirect: 'error', signal: AbortSignal.timeout(15000),
        headers: { 'Content-Type': 'application/json', 'X-Homeall-Timestamp': timestamp,
          'X-Homeall-Signature': signature }, body,
      });
      if (response.ok) {
        const result = await response.json() as { message?: { accepted?: boolean; event_id?: string } };
        success = result.message?.accepted === true && result.message.event_id === job.id;
        error = 'WEBHOOK_INVALID_ACK';
      } else error = `WEBHOOK_HTTP_${response.status}`;
    } catch { /* Retry via the outbox without logging secrets or payload details. */ }
    await repository.rpcVoid('api_finish_frappe_notification', {
      p_event: job.id, p_claim: job.claim_id, p_success: success, p_error: success ? null : error,
    });
  }));
}
