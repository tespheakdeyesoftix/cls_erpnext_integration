# Desk support chat

Vue 3 runs inside `/app/chat` (or `/desk/chat` on Desk versions using that prefix). Every data operation goes through authenticated Frappe methods in this folder. Chat history stays in the existing Supabase tables. No Worker API, browser Supabase client, new chat DocTypes, or inbox polling is used.

## Frontend modules and Pinia state

`public/js/chat/App.vue` contains the UI template and a small `<script setup>` block that connects Pinia and the view composable. The separate `App.js` has been removed.

| Module | Responsibility |
| --- | --- |
| `chatStore.js` | Pinia state, computed values, authenticated requests, pagination, sends/retries, shared unread state, realtime and connection lifecycle |
| `useChatView.js` | Template element refs, scrolling, older-page scroll restoration, textarea sizing, keyboard events and file-input handling |
| `App.vue` | Uses `<script setup>` with `storeToRefs`, binds view behavior, and disposes the store on unmount |
| `ContextDetails.vue` | Accessible product/order dialog using the existing context snapshot, with native focus trapping and Escape dismissal |
| `formatters.js` | Customer titles, app labels and date/time formatting |
| `state.mjs` | Pure message normalization, saved-alias preservation and reconciliation helpers |
| `chat.bundle.js` | Installs a fresh Pinia instance for each Desk page mount |

Pinia is an explicit app dependency, pinned to `2.1.7` to match this Frappe installation. DOM elements are not stored in Pinia state. Store disposal removes realtime/browser listeners, timers and watches and revokes temporary photo URLs. Different mounts do not share inboxes, drafts or permission state. No persistence plugin or browser credential storage is used.

Chat fills the viewport below the Desk toolbar, recalculating its available height on layout and viewport changes, including mobile keyboard resizing. Panels, inputs, buttons, and message bubbles have square corners. View details opens the existing product or order snapshot in a modal without an extra API request. The Desk toolbar's Refresh button reloads the chat list with its current search, unread filter, and loaded pages while preserving the open thread and drafts.

## Current verification and diagnosed warning

Read-only REST checks on 2026-10-23 used the configured project host `cqazlydirmewsogwenbr.supabase.co` with the server's existing secret key. The shared `api_admin_chat_send_message` is exposed with its original eight parameters. The active configured admin profile and owner membership are readable. The latest read-only check confirms that PostgREST now exposes the dedicated Frappe send RPC and alias column, and bootstrap reports that replies are enabled for the configured owner.

The previous Frappe adapter incorrectly passed `p_sender_display_name` to the old eight-parameter RPC. A controlled lookup with that extra parameter reproduced HTTP 404 / `PGRST202` before any send function executed. The complete error identified the nine requested parameter names and suggested the existing eight-parameter function. The warning was a **parameter mismatch**, not proof that the old function was absent. The adapter now uses only the new Frappe-specific RPC for both text and photos and never falls back to the old send operation.

REST/OpenAPI reflects PostgREST's visible schema cache; it cannot distinguish an unapplied migration from an installed function hidden by stale cache or missing service-role grants. Verify physical installation with the read-only query below. The UI disables replies whenever the alias column, exact new RPC parameters, or shared prerequisite are not exposed. No chat database migration, function replacement, or customer send was performed here.

Earlier checks verified authenticated Frappe inbox/history access, R2 chat-bucket access using the existing credentials, a private `chat:admin` subscription with the installed SDK, and bridge startup/shutdown with lease release while customer event delivery was suppressed. The local Chat Page definition is synced into `homeall.dev`. The bridge was initially Offline. In the latest send follow-up, the manually started persistent bridge reports Live, its deduplication records show consumption of the three latest customer messages, and an authenticated Desk Socket.IO test received its heartbeat. Those checks verify the server event path; they do not verify receipt on the user's particular browser or Flutter device. Customer delivery and persisted staff names still need an authorized new-message test conversation. A host that forbids persistent Python processes cannot run this bridge; there is no polling fallback.

## Latency fixes and measurements

The previous API performed two extra Supabase profile/membership GETs before every inbox, history, read, send, and photo read RPC. It also created a new HTTP connection for every request. Bootstrap checked the same admin twice. These redundant checks amplified cross-region latency and transient connection failures.

Every Frappe method still checks the enabled session user's read/reply roles before data access. The existing Supabase RPCs enforce the configured admin's active profile/membership, conversation authorization, and reply permissions within their transactions. Frappe no longer repeats those transactional checks with separate GETs before each RPC. Bootstrap checks the configured admin once to report UI capabilities.

HTTP sessions keep cookies and headers separate per thread while sharing the HTTPS connection pool across all request threads in the process. A process fork gets a separate pool. This matters on the development web server, which creates a fresh thread for each HTTP request: a thread-local connection pool alone does not reuse connections between requests. Authentication headers are supplied separately to each request. There are no automatic send retries. Text sends go straight to the dedicated transactional RPC without an OpenAPI lookup when the capability cache expires. Photo uploads still verify the configured admin’s active reply role, readiness, and conversation access before writing private R2 objects; those pre-upload checks remain necessary because R2 writes precede the send transaction.

Further send diagnostics reproduced intermittent 5–10 second cold connections. One traced request spent 10,105 ms in the system's dual-stack DNS lookup, compared with 6 ms connecting and 15 ms negotiating TLS. IPv4 A-record lookups returned in under 1 ms in the comparison. The chat-only HTTPS adapter resolves IPv4 addresses first, tries the returned addresses before any HTTP request is sent, and restores the original hostname before TLS/SNI, certificate verification, and HTTP Host processing. IPv6-only hosts fall back to the standard connector. No IP addresses are hardcoded, no global DNS setting is changed, and certificate verification remains enabled.

After a committed send, the sender receives the saved result before Frappe enumerates recipients and publishes staff Socket.IO notifications. That work runs through Frappe's request `after_response` callbacks, with immediate publishing retained for callers outside a web request. Database customer Broadcast and notification-outbox behavior remains owned by the existing send RPC. Native numeric `Server-Timing` headers (`chat_auth`, `chat_remote`, `chat_send`) distinguish permission checks, remote HTTP time, and the complete text-send method without exposing message text or credentials.

The browser requests the initial inbox together with bootstrap. Opening a thread renders its messages without waiting for a read receipt. Admin send transactions already update shared read state; an older in-flight read is followed by a one-time update to the newest visible message if necessary. Read-update events refresh inbox counts without reloading message history. Known message echoes skip redundant history fetches. Inbox and thread refreshes run independently in parallel, with one in-flight history request per selected conversation and coalesced event bursts. Successful refreshes clear stale thread errors. A message already confirmed by realtime stays confirmed if its HTTP response fails later.

Incoming reply checks reproduced a second message staying invisible indefinitely while a previous inbox refresh was stalled. Inbox refreshes now have an independent lifetime; they cannot hold up later thread updates. Each conversation's in-flight history request records a follow-up refresh if an event arrives after its query started, so an older response cannot hide that reply. Selection changes can start their own conversation request while an earlier conversation is still loading.

Local realtime notification failures cannot turn a committed Supabase send/read into an HTTP failure. The persistent bridge forwards minimal IDs after checking current Frappe recipients, without remote profile/membership or stored-sender lookups on the relay path. Supabase membership is checked at bridge startup and in each permission-checked content RPC. Stored sender and membership checks for Frappe bell notifications run in `bridge.notify_customer_message` on the existing `short` worker queue, which then uses Frappe's existing deduplicated notification helper. The worker rechecks current recipients, and admin echoes create no bell. A notification enqueue failure is logged without disconnecting live delivery. Relay work uses a worker thread with a fresh site/database context, leaving the websocket listener responsive. R2 contracts are unchanged; no periodic data polling was added.

The updated ID relay reached an authenticated Desk Socket.IO client in 266 ms in a local smoke test, using a context refresh for an existing conversation without inserting a chat message. The short worker completed a verification job using nonexistent test message IDs without creating a bell. Browser regressions cover a second incoming reply while the inbox is held, plus a reply arriving during an older history response. Restart a manually running bridge after Python changes; the standalone process does not reload itself. Refresh the Desk page after building the frontend assets.

### Standalone LAN development access

The actual user URL is `http://192.168.10.101:8887/desk/chat`, served by a separate `bench --site homeall.dev serve --host 0.0.0.0 --port 8887` process. That process did not set `window.dev_server`, so the standard Desk client tried `/socket.io` on web port 8887 and failed with `xhr poll error`. The actual Socket.IO port is 9002. Disconnected chat clients on an explicit HTTP development port now use the configured `frappe.boot.socketio_port` and supply `X-Frappe-Site-Name` during the polling handshake. The canonical site header is needed when the browser hostname is a LAN IP rather than the site's name. Existing connected/proxied Socket.IO connections are kept intact.

Chat handles `connect_error`, retries connections with bounded exponential delay, reconnects on focus/online recovery, and fetches missed messages after connecting. A connection failure immediately shows Offline instead of retaining a previous Live label. Unmounting removes error listeners and cancels retry timers without disconnecting Desk's shared socket.

The app's supported `persistent_cache_keys` hook preserves the bridge lease, message-deduplication keys, and expiring health value during ordinary site cache clearing. Without this hook, `bench clear-cache` removed the live bridge's lease and its ownership check correctly stopped the process. A separate test lease survived a real site cache clear after installing the hook. Capability caches are still cleared normally.

This bench's internal web server listens on `127.0.0.1:12132`. Socket.IO was constructing its authentication callback with the LAN host and port 12132, where the connection is refused. The existing bench configuration `webserver_host` is now `127.0.0.1`, so Socket.IO will use the reachable loopback server and its existing tenant header for authentication. Restart the Socket.IO process after changing this value; its configuration is read at process startup. This is a bench configuration value, not a new database field or API-project change. For a Socket.IO process managed by `bench start`, restart that development process manager and then ensure the chat bridge is running.

After the manual development-bench restart, the actual LAN URL was verified with normal browser headers against the existing Socket.IO service on port 9002, without a test port override. The browser connected to the `homeall.dev` namespace and displayed Live with the separately started bridge running. An existing customer reply, initially withheld from the test client's history responses, appeared after an ID-only context refresh through the bridge relay, Redis, Socket.IO, and authenticated history API in 0.93 seconds. No new customer message, read cursor, or bell was written, and the temporary test session was removed. This verifies browser delivery through the restarted service; it does not simulate a new Flutter send or replace verification of that device's upstream broadcast.

Read-only timing samples from this environment:

| Operation | Before | After |
| --- | --- | --- |
| Bootstrap | 9,885 ms, inbox fetched separately | 2,245 ms including initial inbox |
| Inbox page | 1,225 ms, three Supabase requests | 232 ms, one Supabase RPC |
| Message history | 1,779 ms, three Supabase requests | 165–442 ms per conversation, one RPC each |

All nine available conversation histories loaded successfully in the after-check. These are individual network-dependent samples, not a latency guarantee. No live customer messages or read states were written during measurement. Future HTTP failures record the request duration, endpoint, HTTP status, redacted PostgREST error, and transport exception class in `homeall_chat.log`. A specific historical exception behind the screenshots could not be recovered from the available logs; the request/refresh issues above were verified in code and regression tests.

The send follow-up used the actual authenticated development HTTP endpoint and replayed an existing saved text message with its original client UUID and identical content. It did not insert or deliver a new customer message. Before the DNS fix, the timing headers captured a 5,283 ms remote request. After the DNS fix, the first HTTP replay took 575 ms and the next five took 184–275 ms. These measurements verify HTTP acknowledgement and the idempotent retry path, not new-message insert latency or receipt on a Flutter device. Independent cold-connection probes also encountered a TCP timeout; connection pooling and DNS changes cannot guarantee delivery through an unavailable upstream network.

## Server configuration and permissions

Reuse the existing site configuration through `frappe.conf`:

- `supabase_url`, `supabase_service_role_key`, `supabase_admin_user_id`.
- Existing grouped `r2_storage.account_id`, `access_key_id`, `secret_access_key`, or their existing legacy `r2_` equivalents. Chat uses the existing R2 client with the **fixed private bucket** `homeall-chat-staging`, independent of the public item-image bucket and public URL. The credentials must have access to this additional bucket.

The configured Supabase admin must have an active profile and active owner/manager/operator/viewer membership. Viewer membership cannot send. Frappe callers must be enabled System Users. Read and reply roles both default to System Manager; all API methods enforce them before external calls. The Page ships with System Manager access. To allow another role, update the Page's allowed roles in Desk and configure explicit lists, for example:

```json
{
  "chat_read_roles": ["System Manager", "Support Viewer", "Support Operator"],
  "chat_reply_roles": ["System Manager", "Support Operator"]
}
```

No user ID or alias is accepted from the browser. `p_user` always comes from server configuration. Staff names are snapshots from the authenticated Frappe User `full_name`, falling back to the User identifier. Shared Supabase read state means one staff member reading a thread marks it read for all staff; a user-scoped Frappe event refreshes their inboxes. Frappe Notification Logs remain per-recipient bell notifications, with generic text and an authorized chat link.

## Verified API contract and read-only installation check

The database changes are owned by the API app. Do not recreate, drop, rename, overload, or change the signature of the existing shared `public.api_admin_chat_send_message(uuid,uuid,uuid,text,text,text,text,integer)`. Its prerequisite is `20261003001900_business_chat.sql`, including its existing profile/admin membership, conversation/message/read-state, notification outbox, and broadcast dependencies from that project's migration chain. If the prerequisite is missing or has drifted, the API app must restore its real migrations and dependencies rather than install a stub.

The API app provides `20261023000100_frappe_chat_staff_alias.sql`. That migration adds nullable `public.chat_messages.sender_display_name` and the dedicated `public.api_frappe_admin_chat_send_message`, delegating to the existing shared transaction. History and existing V2 Broadcast message serialization include the saved alias.

Run this read-only query in the **configured project's** Supabase SQL editor:

```sql
select
  to_regprocedure(
    'public.api_admin_chat_send_message(uuid,uuid,uuid,text,text,text,text,integer)'
  ) as existing_send_rpc,
  to_regprocedure(
    'public.api_frappe_admin_chat_send_message(uuid,uuid,uuid,text,text,text,text,text,integer)'
  ) as frappe_send_rpc;
```

Interpretation:

- Both exist: verify the exact request name/parameters, service-role permissions, configured project URL, and PostgREST schema cache. Do not create duplicates.
- Only the shared RPC exists: deploy the API app's `20261023000100_frappe_chat_staff_alias.sql` through its normal deployment process.
- Shared RPC absent: investigate prerequisite `20261003001900_business_chat.sql` and its dependencies/schema drift before enabling sends.
- After installation, if the schema cache is stale, the database owner can run `NOTIFY pgrst, 'reload schema';` and revisit Chat after the 60-second capability cache expires.

### Frappe send request

Both text and photo replies call **only** `public.api_frappe_admin_chat_send_message` through the existing authenticated server-side REST adapter. It uses `frappe.conf.supabase_service_role_key`; no browser Supabase credentials are used. The new RPC is service-role-only.

| Parameter | Type | Required/value |
| --- | --- | --- |
| `p_user` | `uuid` | Required; configured shared `supabase_admin_user_id`, always assigned server-side |
| `p_conversation` | `uuid` | Required; existing conversation UUID |
| `p_client_message` | `uuid` | Required; stable across retries |
| `p_kind` | `text` | Required; `text` or `photo` |
| `p_sender_display_name` | `text` | Required; trimmed Frappe User full name, 1–255 characters, with User identifier fallback for a blank name |
| `p_body` | `text` | Nullable; text content for text messages, null for photos |
| `p_media_key` | `text` | Nullable; private R2 object key for photos, otherwise null |
| `p_media_type` | `text` | Nullable; validated photo MIME type, otherwise null |
| `p_media_size` | `integer` | Nullable; original photo byte count, otherwise null |

Return the saved message's existing fields plus nullable `sender_display_name`. The server's saved result is canonical. Preserve the send transaction's authorization, idempotency, summaries, shared read state, notification outbox, and existing broadcasts. Retries use the original client UUID and identical content/media and return the original saved alias, even after a staff rename. Text/photo calls never retry through the old RPC.

Frappe checks exact parameter names and column exposure, without executing a send. Backend HTTP failures log the configured project host, endpoint, parameter **names**, HTTP status, and full PostgREST JSON error to the site/bench `homeall_chat.log`, with Supabase keys, bearer JWTs and authorization fields redacted. No request content or credentials are logged. Browser errors contain generic actionable guidance; `PGRST202` is identified as a request/cache mismatch, not automatic proof of a missing SQL function.

History, pagination, send responses, optimistic reconciliation, realtime fetches, and reconnect catch-up retain the saved alias. Legacy messages display “Support”; whitespace-only names also display “Support”. A later legacy response without an alias cannot erase a known saved alias. Pending names are never used to fill in an absent alias on an authoritative saved result. Names use Vue interpolation, including on photo bubbles; the shared Supabase ID never causes all staff messages to be labelled “You”. The bridge still forwards only minimal IDs to authorized Frappe user rooms.

No new SQL implementation or migration files are generated by this Frappe change.

## Desk UI components

Chat uses the installed Frappe UI Button, TextInput, Input, Avatar, Badge, LoadingIndicator and Dialog components. Page-scoped styles map these controls to Desk color, border, typography and radius variables, including dark mode; no global Tailwind reset is introduced. Details and photo dialogs use Headless UI focus management through Frappe UI, support Escape, and return focus when closed. The reply field updates on input and keeps the existing multiline/Enter behavior and automatic height. Mobile navigation and the independent inbox/thread scroll regions remain unchanged.

## Build and start

From the bench directory:

```sh
bench setup requirements
bench build --app homeall_ecommerce_integration
bench --site homeall.dev clear-cache
bench restart
```

The existing build scans `public/js/chat/chat.bundle.js` and `chat.bundle.css`. The Desk Page loads these assets on demand. No separate Vue server or Vuetify is needed. Python dependencies are already in the app's pyproject (`supabase`, `Pillow`, `boto3`); `requests` is provided by Frappe and `realtime` by the Supabase client.

Development: leave the normal Frappe web, Socket.IO, Redis, and workers running. In another terminal from the bench directory:

```sh
env/bin/python -m homeall_ecommerce_integration.homeall_ecommerce_integration.page.chat.bridge \
  --site homeall.dev --sites-path sites
```

The command resolves the sites directory before initializing Frappe and closes site/database context on exit. SIGINT/SIGTERM shut it down gracefully. It uses a Redis lease scoped to the site's database, renews it, and exits rather than running after losing ownership. Never run a bridge as a scheduler job or web request.

Production: choose **one** of `deploy/supervisor.conf` or `deploy/homeall-chat@.service`, adjust the bench path, OS user, and site, and install it using your normal service management. These are examples, not automatically installed services. After code changes, restart the bridge separately using the service you installed: `sudo supervisorctl restart homeall-chat-homeall.dev` or `sudo systemctl restart homeall-chat@homeall.dev`. For a manually started development bridge, stop and rerun its command. Keep Redis, workers, and Socket.IO running. Do not put secrets in commands or unit files.

## Private Realtime authentication and delivery

The bridge subscribes only to existing **private Broadcast** `chat:admin` events `message_created` and `context_updated`; it does not use Postgres Changes. The installed SDK was inspected and an actual private join succeeded with the API key in the gateway `apikey` query parameter and **no** `access_token` for the configured `sb_secret_…` key. It never treats that key as a JWT. Legacy service-role JWT keys also work as access tokens. An optional server-only `supabase_realtime_access_token` can override channel authentication if another deployment requires a valid JWT; supply/rotate it through secure server configuration and restart the bridge before expiry. It is not needed for the verified project. A rejected join causes Reconnecting status and bounded exponential retries; it does not fall back to public channels.

See the official [Realtime protocol](https://supabase.com/docs/guides/realtime/protocol) and [API key documentation](https://supabase.com/docs/guides/getting-started/api-keys) for the distinction between gateway API keys and JWT access tokens.

Minimal validated conversation/message IDs are published to individually authorized Frappe user rooms. Frappe clients fetch data through the same permission checks as initial loads. V2 and legacy events are accepted. Message IDs are deduplicated in Redis for 24 hours. Reconnects and browser visibility/focus recovery trigger one catch-up, including pagination through gaps larger than 100 messages. Health heartbeats update the connection indicator; a browser-local watchdog detects a dead bridge without data polling. If Socket.IO itself is disconnected, the indicator is Offline. Scroll position, older history, drafts, and pending messages survive live reconciliation. Leaving the page removes Socket.IO, browser, timer, and Vue handlers.

Incoming stored customer messages create generic Frappe Notification Logs for authorized staff using Frappe's existing notification queue and bell. Notification links are deduplicated by message/recipient. Admin echoes do not create bell notifications. New notifications only cover events consumed by the bridge; messages missed while it was down are recovered into the inbox by catch-up, not replayed as historical bell notifications.

## Private photos and retries

Photos are multipart uploads to `chat.send_photo` with `conversation_id`, `client_message_id`, and `file`. Authorization precedes upload. Actual image decoding verifies JPEG/PNG/WebP, the 8 MiB bound, and a 40-megapixel resource bound. Original bytes are preserved; public-image optimization is not used. The object key is:

```text
chat/{conversation_id}/{client_message_id}-{sha256(original_bytes)[:24]}.{jpg|png|webp}
```

The bucket is always `homeall-chat-staging`, and objects use `private, no-store`. Confirm in Cloudflare that the bucket has no public domain or public `r2.dev` access. S3 access alone does not verify that setting.

The photo message uses the dedicated atomic `api_frappe_admin_chat_send_message` RPC. Uncertain outcomes retain the original object, and retries use the same client UUID, fingerprint and bytes. Do not delete an uploaded object merely because an RPC timed out; it may already be referenced by a committed message. An uncommitted upload may remain orphaned; cleanup needs an audited database-reference check and is intentionally not an automatic delete-on-error action.

Photo reads accept **only a message UUID**, call `api_chat_media` for authorization, and return an authenticated private Frappe image response. No arbitrary object-key endpoint, public URL, or persisted expiring URL exists. Portal `/chats/media/…` URLs are replaced by the local authorized endpoint. Existing customer objects require no Frappe-specific ownership metadata.

## Tests and acceptance

Offline checks from the app directory:

```sh
../../env/bin/python -m unittest homeall_ecommerce_integration.homeall_ecommerce_integration.page.chat.test_chat -v
node --test homeall_ecommerce_integration/public/js/chat/state.test.mjs
```

Tests cover denied Frappe users, read-only Supabase membership, server-derived aliases, retry identity, history aliases, private media authorization, byte validation/fingerprints, uncertain outcomes, scoped realtime events, event deduplication, shared reads, and echo/pending/history reconciliation. RPCs and R2 are mocked; these tests do not prove the remote SQL transaction.

Optional browser checks use the compiled production assets with mocked Frappe/Supabase data. With Playwright and its Chromium browser installed, run:

```sh
python homeall_ecommerce_integration/homeall_ecommerce_integration/page/chat/browser_checks.py
```

Validation passed: 54 Python tests, 15 JavaScript tests, Ruff, production asset compilation, and browser checks for desktop/mobile layout, deployed product/order context shapes, plain text rendering, echo/retry reconciliation, a 140-message reconnection gap, preserving a scrolled reader's position, Socket.IO recovery, selection races, search, listener cleanup, staff-name trimming/legacy fallbacks, saved-name preservation after staff renaming and an uncertain send, photo alias rendering/previews, aliases surviving reload/pagination, Pinia state isolation between mounted pages, per-conversation draft updates, disposal of Pinia watchers without further network requests, bundled startup, nonblocking read receipts, independent inbox/thread refreshes, replies arriving during in-flight history requests, coalesced read events, transient-error recovery, and realtime-confirmed sends after an HTTP failure. The send follow-up adds regression checks for sharing connections across fresh request threads while isolating session state, fork isolation, scoped DNS behavior, retaining the TLS hostname, IPv6 fallback, timing headers, and deferring staff notifications until after the send response. Incoming reply regressions verify that remote lookups stay off the ID relay path, that the notification worker rechecks membership and suppresses admin echoes, and that a notification queue failure cannot undo live delivery.

After the API app deploys the required contract and the bridge is running, verify with a designated test customer/conversation:

- Text and photo sends reach the existing customer application; retries save one row and preserve the original alias after staff renaming.
- Stored names survive page reload; photos uploaded by either application open in the other. Verify private bucket settings and bucket-scoped credentials.
- Incoming customer text/photo and context updates arrive without refresh, update ordering and badges, and produce authorized Frappe bell notifications.
- Two staff sessions share read state. Viewers cannot send; other Desk users cannot call data/media methods or receive chat events.
- Search, All/Unread, inbox/history pagination, context snapshots, mobile back navigation, multiline input, upload rejection, failed retries, and enlarged photos work. No external order URL is invented; no unverified record mapping is linked.
- Stop/restart the bridge and disconnect/reconnect Socket.IO; catch-up preserves older history, reconciles pending sends, and leaves a scrolled reader's position intact. Navigate away/back repeatedly and confirm only one listener/mount remains.
- Inspect network responses and assets for credentials. Only authenticated Frappe methods and private local media URLs should reach the browser.
