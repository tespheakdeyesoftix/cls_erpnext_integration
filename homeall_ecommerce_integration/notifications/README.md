# Homeall order and chat notifications

The app uses Frappe Notification Log for the bell and Firebase Cloud Messaging for subscribed browsers. All enabled System Users can read chats; `chat_reply_roles` still controls replies (default: System Manager). `chat_read_roles` no longer restricts reading. Website Users and disabled users cannot register devices or access order/chat endpoints.

## Site configuration

Add the following object to the target site's **private** `site_config.json`. Keep `enabled` false until the Frappe migration, Worker migration, HTTPS endpoint and credentials are ready.

```json
{
  "homeall_notifications": {
    "enabled": false,
    "push_enabled": true,
    "firebase_web_config": {
      "apiKey": "PUBLIC_FIREBASE_WEB_API_KEY",
      "authDomain": "PROJECT.firebaseapp.com",
      "projectId": "PROJECT",
      "storageBucket": "PROJECT.firebasestorage.app",
      "messagingSenderId": "SENDER_ID",
      "appId": "WEB_APP_ID"
    },
    "firebase_vapid_public_key": "PUBLIC_WEB_PUSH_CERTIFICATE_KEY",
    "firebase_service_account": {
      "type": "service_account",
      "project_id": "PROJECT",
      "private_key_id": "KEY_ID",
      "private_key": "-----BEGIN PRIVATE KEY-----\nPRIVATE_KEY_CONTENT\n-----END PRIVATE KEY-----\n",
      "client_email": "SERVICE_ACCOUNT@PROJECT.iam.gserviceaccount.com",
      "token_uri": "https://oauth2.googleapis.com/token"
    },
    "webhook_secret": "REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS",
    "push_ttl_seconds": 3600
  }
}
```

Use the web app configuration and VAPID public key from Firebase Cloud Messaging. The service account needs permission to send FCM messages. The web config and service account must use the same Firebase project. Enable the FCM HTTP v1 and registration APIs. Private keys must contain real PEM line breaks after JSON decoding. Never put site configuration or tokens in source control. Browser responses allowlist public web config fields and never expose the service account or webhook secret.

FCM tokens are encrypted using Frappe Password fields. Back up the site's encryption key with the database. Browser installations are bound to the authenticated Frappe user and a hash of the login session. Explicit logout disables that session's registrations; closing a tab leaves them enabled. Token refresh preserves the installation, and delivery generation checks prevent old queued work from being sent to a different account.

## Install and activate

From the bench directory, install dependencies and migrate the chosen site:

```sh
bench setup requirements --python
cd apps/homeall_ecommerce_integration
yarn install --frozen-lockfile
cd ../..
bench build --app homeall_ecommerce_integration
bench --site YOUR_SITE migrate
bench --site YOUR_SITE clear-cache
bench restart
```

Restart the separately managed chat bridge as well. The normal Frappe queue workers, Redis, Socket.IO and scheduler must run. `homeall_notifications.enabled` switches the bridge's bell producer to the webhook pipeline; the bridge continues live chat delivery. Drain old notification jobs before activation to avoid overlapping producers during rollout.

In `homeall-ecommerce-api`, apply `20261024000100_frappe_notifications.sql` using the normal Supabase deployment workflow. It creates a separate transactional outbox and service-role-only claim/finish/replay RPCs; it does not backfill historical events. Add these Worker settings independently of its existing Firebase credentials:

If the API project is managed on another PC, copy the [API handoff files](api_handoff/README.md). This includes the migration SQL, dispatcher source, exact table fields, and the required Worker integration changes. These settings belong in Worker environment variables/secrets, not KV.

- `FRAPPE_NOTIFICATION_WEBHOOK_URL`: `https://YOUR_SITE/api/method/homeall_ecommerce_integration.notifications.api.receive_event`
- `FRAPPE_NOTIFICATION_WEBHOOK_SECRET`: the same random secret as `webhook_secret` in the site config, stored as a Worker secret.

Deploy the Worker through the API repository's normal staging/production process. Enable the site integration once both sides are ready. When disabling, disable the upstream dispatcher as well if you intend to stop accumulating ERPNext jobs. Existing portal and customer-app push queues are unaffected.

There is one ERPNext webhook destination per API environment. Do not share webhook secrets across environments. The endpoint must be reachable by the Worker using HTTPS; a private LAN-only ERPNext site needs a reachable HTTPS endpoint. No configuration values, live migrations, or deployments are applied by the source-code implementation itself.

## User flow and platform behavior

The global Desk bundle checks each browser registration and presents Enable notifications / Later on every Desk load or route navigation until registration succeeds. There is no standalone Browser notifications button. Later, the close button, or Escape dismisses the modal for the current visit only; the next navigation or reload shows it again. Old saved snoozes and opt-out flags do not suppress the modal. Browser permission is requested directly inside the Enable click. Blocked permission shows browser/OS settings instructions in the modal without automatically requesting permission again. A previously disabled browser with granted permission requires an explicit Enable click. Administrators can disable registrations using the existing authenticated unregister endpoint; no global preference button is injected. Foreground push shows generic in-app text; the Frappe realtime event owns bell updates. Background data-only FCM messages are displayed once by the Firebase service worker with a stable event tag. Network uncertainty can cause push retries; FCM does not provide exactly-once delivery.

The worker is served from the public `notifications.api.service_worker` method with JavaScript MIME and an explicit scope header. Its isolated `/homeall-push/` scope avoids replacing other root service workers. Its Firebase registration is passed explicitly to `getToken`. Native notifications and the web-app manifest use the cropped red DSKU logo in 192/512px icons; a 180px Apple touch icon is supplied when the site has no existing one. Icon filenames and the manifest URL are versioned when replacing artwork to avoid reusing cached branding. It does not cache authenticated Desk pages or enable offline ERPNext access.

- Windows Chrome/Edge can show native alerts with the ERPNext tab closed while browser background delivery remains available. A fully exited browser is not guaranteed to receive immediately.
- Android uses the browser's system push service; battery, OS and notification settings can affect delivery.
- iOS/iPadOS 16.4+ requires Add to Home Screen and opening Homeall from that installed icon. The app shows installation guidance outside standalone mode. An installed web app displays alerts in the phone's Notification Center/Lock Screen.

Notifications contain generic text, not customer names, messages, order totals or private media. Clicking focuses/navigates an ERPNext window or opens one. Approved destinations are `/desk/online-order?order=UUID` and `/desk/chat?conversation=UUID&message=UUID`, with an additional `homeall_event` identifier. A narrowly scoped guest redirect hook preserves validated order/chat identifiers across login, including this framework version's path-only Desk login redirect. Orders are fetched by UUID independently of list filters; chat opens the corresponding conversation. The app marks the recipient's bell entry read only after the destination loads successfully. Clicking the standard Frappe bell also uses its native read behavior.

## Recovery and monitoring

The webhook verifies HMAC-SHA256 over `timestamp + '.' + exact_raw_body`, accepts timestamps within five minutes, and only accepts order_created/chat_message events. Source titles/destinations/customer content are discarded. It acknowledges after the database transaction commits. Duplicate event UUIDs are harmless. Outbox insertion happens in the same transaction as the upstream source event, so rolled-back orders/messages cannot produce notifications.

Frappe locks each event while creating bell logs and delivery rows in one transaction. Each device delivery has its own attempts, next retry, lease and error class. Claims are committed before contacting Firebase. Crashed workers are recovered after five minutes; transient failures retry up to eight attempts. Confirmed unregistered/project-mismatched tokens are disabled. Old push deliveries are skipped after their configured TTL, while bell history is retained. No old events are backfilled to users or devices added later.

System Managers can call `homeall_ecommerce_integration.notifications.worker.health` to inspect pending/failed counts and oldest pending event. Inspect Homeall Notification Event and its delivery rows in Desk. Replay exhausted local deliveries with POST `worker.replay(event_id)`. Expired push work remains expired on replay; its bell history is still available. Upstream failures are visible in `frappe_notification_outbox`; use service-role-only `api_replay_frappe_notification(p_event)` to retry exhausted webhook jobs. Inspect `last_error`, oldest pending `created_at`, attempts and status. No exception messages containing tokens or credentials are retained.

## Retention through Log Settings

In Desk, open **Log Settings**, add **Homeall Notification Event**, set **Clear Logs After (days)** to **90**, and save. The controller implements Frappe's `clear_old_logs` interface, so no migration or new table is required for this support. Restart Python processes after deploying the code and refresh Log Settings if the DocType is not listed yet. Homeall Notification Delivery is a child table; configure its parent Event rather than adding Delivery separately.

Also set **Notification Log** to your desired bell-history retention, such as **90 days**. That setting affects all apps' bell notifications. Homeall cleanup never deletes Notification Log records itself. It waits until an event's bell records have been cleared, so links can still mark those notifications read. Consequently, a longer bell-history retention also delays Homeall delivery cleanup.

Frappe's scheduled log cleanup compacts at most 5,000 eligible events per run in batches of 250. Only Ready events whose own modification and every delivery's modification are older than the configured period qualify. Pending events, Pending/Sending/Failed deliveries, and events with existing bell records are preserved. Resolve failed deliveries before they become eligible. Zero days disables Homeall cleanup.

For eligible events, cleanup removes the child delivery records, payload, and destination. It retains one small event row (UUID, event type, generic title, timestamps and Ready status) as a permanent deduplication marker; it does not delete the event identity. This prevents an upstream replay from recreating notifications. The retained event has an empty Deliveries table. Actual orders, chat messages, push subscriptions and upstream Supabase records are unaffected. No retention policy is enabled or live history deleted merely by deploying this code; save the desired entry in Log Settings to enable it.

## Verification

Offline application checks:

```sh
../../env/bin/python -m unittest homeall_ecommerce_integration.notifications.test_notifications homeall_ecommerce_integration.homeall_ecommerce_integration.page.chat.test_chat
node --test homeall_ecommerce_integration/public/js/notifications/policy.test.mjs homeall_ecommerce_integration/public/js/chat/state.test.mjs
python homeall_ecommerce_integration/notifications/browser_checks.py
```

The browser check requires built app assets and Playwright with Chromium. It compiles the real notification sources against mocked Firebase services and exercises the production order bundle. The API repository's `npm run check` includes PostgreSQL/PGlite tests for transactional rollback, role permissions, leases, stale acknowledgements, retries and replay. `npm run build` is a Worker deployment dry run.

Before production activation, run a migrated staging site with real credentials. Verify multiple staff/devices, bell updates without push consent, denied permission, logout/account switching, changing order filters, reload/login links and missing records. Stop/restart ERPNext workers and the API dispatcher to check recovery. Finally test actual background/closed-tab delivery and clicks on Windows, Android and an installed iPhone web app. Automated mocked browser checks do not establish actual OS delivery or deployed Firebase configuration.
