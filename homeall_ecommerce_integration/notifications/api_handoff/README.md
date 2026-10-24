# Copy to the API project on the other PC

These files are a handoff for `homeall-ecommerce-api`; they do not run inside the Frappe app. No remote database or Worker deployment is performed by copying this folder.

## Database migration

Copy `20261024000100_frappe_notifications.sql` to the API project's `supabase/migrations/` directory. It requires the existing `admin_notification_events` table and `private` schema from the admin-notifications migration. Read-only prerequisite check:

```sql
select to_regclass('public.admin_notification_events') as source_events,
       to_regclass('public.frappe_notification_outbox') as existing_outbox;
```

If the outbox migration is already applied on the other PC/project, use that existing migration instead of adding the same objects again. Keep already-applied migration history intact.

The new table is `public.frappe_notification_outbox`:

| Column | SQL type | Purpose/default |
| --- | --- | --- |
| `event_id` | `uuid` | Primary key and FK to `admin_notification_events.id`; one delivery job per source event. |
| `status` | `text` | `pending`, `processing`, `sent`, `failed`; default `pending`. |
| `attempts` | `integer` | Attempts made; default `0`. |
| `next_attempt_at` | `timestamptz` | Retry time; default current time. |
| `claimed_at` | `timestamptz` | Processing lease start; nullable. |
| `claim_id` | `uuid` | Lease identity, protecting against stale worker acknowledgements; nullable. |
| `last_error` | `text` | Sanitized failure code; nullable. |
| `sent_at` | `timestamptz` | Successful webhook acknowledgement time; nullable. |
| `created_at` | `timestamptz` | Job creation time; default current time. |

The migration also adds an after-insert trigger on `admin_notification_events` and three service-role-only RPCs: `api_claim_frappe_notifications`, `api_finish_frappe_notification`, and `api_replay_frappe_notification`. It queues new `order_created` and `chat_message` events transactionally, with five-minute leases and eight maximum attempts. It does not add columns to orders/chat tables, backfill existing events, or alter the portal/customer notification queues. RLS is enabled and browser roles have no access to the outbox or its RPCs.

From the API project, use the project's existing Supabase deployment workflow. For an already-linked staging project:

```sh
npx supabase migration list
npx supabase db push --dry-run
npx supabase db push
```

`db push` applies all pending migrations shown by the dry run, so review that list against the intended project's migration history. Do not run a database reset on the hosted project.

## Worker settings: variables and secrets, not KV

The dispatcher reads `config.FRAPPE_NOTIFICATION_WEBHOOK_URL` and `config.FRAPPE_NOTIFICATION_WEBHOOK_SECRET` from parsed Worker environment bindings. It never reads these values from `CONFIG_KV`.

| Name | Where to configure | Value |
| --- | --- | --- |
| `FRAPPE_NOTIFICATION_WEBHOOK_URL` | Worker environment variable, type Text | `https://khmart-007.aagj7.com/api/method/homeall_ecommerce_integration.notifications.api.receive_event` |
| `FRAPPE_NOTIFICATION_WEBHOOK_SECRET` | Worker environment secret, type Secret | Exactly the existing `homeall_notifications.webhook_secret` value in ERPNext's private `site_config.json`. |

Dashboard: **Workers & Pages → your API Worker → Settings → Variables and Secrets**. Select the intended staging/production Worker. Set the two values there, then deploy through the project's usual workflow. They are separate from the Worker's existing Firebase credentials.

Alternatively, merge the URL into the selected environment's existing `vars` in `wrangler.jsonc` without replacing other variables. For example, inside `env.staging.vars`:

```json
{
  "FRAPPE_NOTIFICATION_WEBHOOK_URL": "https://khmart-007.aagj7.com/api/method/homeall_ecommerce_integration.notifications.api.receive_event"
}
```

Set the corresponding secret interactively from the API project:

```sh
npx wrangler secret put FRAPPE_NOTIFICATION_WEBHOOK_SECRET --env staging
```

Paste the matching existing ERPNext webhook secret at the prompt. Use `--env production` only for the corresponding production configuration. Do not commit the secret to Wrangler vars, KV exports, source control, or browser code. Do not use a Firebase API key/private key or an ERPNext password for this shared secret. For local `wrangler dev`, use an ignored `.dev.vars` file with both bindings.

`wrangler secret put` immediately creates and deploys a Worker version. For a staged version rollout, use `wrangler versions secret put` and the project's normal version-deployment workflow instead. Configure both values together before activating code that requires the pair.

## Worker code changes are required too

Applying SQL and adding settings does not send any webhooks by itself. Copy `notifications.ts` to `src/services/frappe/notifications.ts`; it uses the API project's existing Zod 4, RuntimeConfig and Repository interfaces.

Add these optional fields to `EnvSchema` in `src/config/env.ts` so the parsed RuntimeConfig retains the bindings:

```ts
FRAPPE_NOTIFICATION_WEBHOOK_URL: z.url().refine(
  (value) => value.startsWith('https://'), 'HTTPS required',
).optional(),
FRAPPE_NOTIFICATION_WEBHOOK_SECRET: z.string().min(32).optional(),
```

In the existing `superRefine` callback, require both or neither:

```ts
if (Boolean(env.FRAPPE_NOTIFICATION_WEBHOOK_URL) !== Boolean(env.FRAPPE_NOTIFICATION_WEBHOOK_SECRET)) {
  ctx.addIssue({
    code: 'custom', path: ['FRAPPE_NOTIFICATION_WEBHOOK_URL'],
    message: 'Configure both Frappe webhook settings',
  });
}
```

Import `processFrappeNotifications` into `src/index.ts`, and include `processFrappeNotifications(config, repository)` in the existing scheduled handler's `ctx.waitUntil(Promise.all([...]))`. Retain the existing one-minute cron and other scheduled jobs.

For immediate delivery, call the dispatcher through `c.executionCtx.waitUntil(...)` after committed order creation and customer chat/photo operations, including DSKU chat routes. Add this to the existing post-commit notification helpers in `modules/orders/orders.routes.ts`, `modules/chat/chat.routes.ts`, and `modules/dsku/dsku.routes.ts`, using the appropriate relative import:

```ts
if (c.get('config').FRAPPE_NOTIFICATION_WEBHOOK_URL) {
  c.executionCtx.waitUntil(processFrappeNotifications(c.get('config'), c.get('repository')));
}
```

Keep the Frappe dispatcher outside any `FIREBASE_PROJECT_ID` condition: Frappe sends its own FCM messages. Inserts made through other paths are recovered by the cron. Retain existing portal/customer push dispatchers.

## Wire contract and acceptance checks

The dispatcher POSTs `{id, type, created_at, payload}`. `id` is the source event UUID; `created_at` is a timestamp with timezone. Order payloads contain `order_id`; chat payloads contain `conversation_id` and `message_id`. All identifiers are UUIDs.

Headers: `X-Homeall-Timestamp` is current Unix time in seconds; `X-Homeall-Signature` is the lowercase hex HMAC-SHA256 of `timestamp + '.' + exact UTF-8 request body`. Each retry gets a new timestamp/signature. ERPNext accepts a five-minute clock window and acknowledges only after persistence with `{message: {accepted: true, event_id: UUID}}`.

On the other PC run the API's typecheck/tests/build before deploying. Confirm on staging that a new committed order/customer message creates an outbox job, reaches ERPNext's Homeall Notification Event, and becomes `sent` only after a matching acknowledgement. Duplicate deliveries must produce one ERPNext event/bell per recipient. Check retry after an unavailable ERPNext endpoint and recovery of expired leases. No new customer message or test order is generated by these handoff files.

Official references: [Cloudflare Worker variables](https://developers.cloudflare.com/workers/configuration/environment-variables/), [Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/), and [Supabase migrations](https://supabase.com/docs/guides/deployment/database-migrations).
