import { computed, markRaw, onScopeDispose, reactive, ref, watch } from 'vue';
import { defineStore } from 'pinia';
import { clientMessageId, mergeMessages, sortConversations } from './state.mjs';
import { listenForRoutes } from '../notifications/policy.mjs';

// A separate Pinia instance is installed for each Desk page mount.
// DOM operations are supplied by useChatView and never enter store state.
export const useChatStore = defineStore('homeall-chat', () => {
	const API = 'homeall_ecommerce_integration.homeall_ecommerce_integration.page.chat.chat.';
	const inbox = ref([]), totalUnread = ref(0), search = ref(''), unreadOnly = ref(false);
	const selected = ref(null), mobileThread = ref(false), loadingInbox = ref(true), loadingThread = ref(false);
	const inboxError = ref(''), threadError = ref(''), actionError = ref(''), setupNotice = ref('');
	const canSend = ref(false), displayName = ref('Support'), bridgeStatus = ref('Connecting');
	const socketConnected = ref(true), offline = ref(!navigator.onLine);
	const inboxCursor = ref(null), inboxMore = ref(false), loadingMore = ref(false);
	const threads = reactive({}), drafts = reactive({});
	const showNew = ref(false), sendingPhoto = ref(false);
	let dead = false, started = false, initializing = false, view = null;
	let selectionVersion = 0, inboxVersion = 0, loadedPages = 1;
	let searchTimer, eventTimer, healthTimer, socketTimer, socketAttempts = 0, heartbeatAt = Date.now();
	let refreshingInbox = false;
	let inboxDirty = false, threadDirty = false, healthRequest = null;
	const threadRequests = new Map();
	const inFlightSends = new Set();
	let readInFlight = '', lastRead = '';
	let stopRoutes = () => {};
	const photoObjectURLs = new Set();
	const active = computed(() => selected.value ? threads[selected.value.id] : null);
	const draft = computed({ get: () => drafts[selected.value?.id] || '', set: (v) => { if (selected.value) drafts[selected.value.id] = v; } });
	const connection = computed(() => offline.value || !socketConnected.value ? 'Offline' : bridgeStatus.value);
	const pinned = computed(() => selected.value?.context);
	const snapshot = computed(() => pinned.value?.snapshot || pinned.value || {});
	const contextType = computed(() => pinned.value?.context_type || pinned.value?.type || selected.value?.kind);
	const contextPrice = computed(() => snapshot.value.price ?? snapshot.value.pricing?.unit_price ?? snapshot.value.product?.price);
	const contextCurrency = computed(() => snapshot.value.currency || snapshot.value.pricing?.currency || '');
	const orderTotal = computed(() => snapshot.value.total ?? snapshot.value.total_amount ?? snapshot.value.order?.total_amount);
	const orderSummary = computed(() => snapshot.value.item_summary || snapshot.value.summary ||
		(snapshot.value.items || []).map((item) => `${item.quantity ?? 1} × ${item.name || item.item_name || 'Item'}`).join(' · '));
	const maySend = computed(() => canSend.value && !offline.value && active.value?.loaded);

	async function call(method, args = {}) {
		const response = await frappe.call({ method: API + method, args, silent: true });
		if (response.exc) throw new Error('Chat request failed. Please retry.');
		return response.message;
	}
	function errorText(error) { return error?.message?.includes('fetch') ? 'Connection lost. Please retry.' : 'Unable to complete this request. Please retry.'; }
	function latestSaved(thread) { return thread?.items.filter((m) => !m._status).at(-1); }
	function threadFor(id) { return threads[id] ||= { items: [], hasMore: false, cursor: null, loaded: false, loadingOlder: false }; }
	function visible() { return !dead && !document.hidden && document.hasFocus() && mobileThread.value; }
	function bindView(bindings) {
		view = bindings;
		return () => { if (view === bindings) view = null; };
	}
	function nearBottom() { return view?.nearBottom() ?? true; }
	async function bottom() {
		await view?.scrollToBottom();
		showNew.value = false;
	}

	function applyInbox(result) {
		inbox.value = sortConversations(result.items);
		totalUnread.value = result.total_unread;
		inboxMore.value = result.has_more;
		inboxCursor.value = result.next_cursor;
		loadingInbox.value = false;
		inboxError.value = '';
	}

	async function loadInbox(reset = true) {
		const version = ++inboxVersion;
		if (reset) { loadingInbox.value = true; loadedPages = 1; }
		inboxError.value = '';
		try {
			let cursor = null, result, rows = [];
			for (let page = 0; page < loadedPages; page++) {
				result = await call('conversations', { search: search.value, unread: unreadOnly.value, cursor });
				if (dead || version !== inboxVersion) return;
				rows.push(...result.items);
				cursor = result.next_cursor;
				if (!result.has_more || !cursor) break;
			}
			applyInbox({ ...result, items: rows });
		} catch (e) { if (!dead && version === inboxVersion) inboxError.value = errorText(e); }
		finally { if (!dead && version === inboxVersion) loadingInbox.value = false; }
	}
	async function moreInbox() {
		if (loadingMore.value || !inboxMore.value) return;
		loadingMore.value = true;
		const version = inboxVersion;
		try {
			const result = await call('conversations', { search: search.value, unread: unreadOnly.value, cursor: inboxCursor.value });
			if (dead || version !== inboxVersion) return;
			inbox.value = sortConversations([...inbox.value, ...result.items]);
			inboxMore.value = result.has_more; inboxCursor.value = result.next_cursor;
			totalUnread.value = result.total_unread; loadedPages++;
		} catch (e) { if (!dead && version === inboxVersion) inboxError.value = errorText(e); }
		finally { loadingMore.value = false; }
	}
	watch([search, unreadOnly], () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadInbox(), 300); });

	async function openConversation(item) {
		const version = ++selectionVersion;
		selected.value = item; mobileThread.value = true; showNew.value = false; actionError.value = ''; threadError.value = ''; lastRead = '';
		const thread = threadFor(item.id);
		loadingThread.value = !thread.loaded;
		try {
			await refreshThread(item.id, version);
			if (dead || version !== selectionVersion) return;
			await bottom(); void markVisible();
		} catch (e) { if (version === selectionVersion) threadError.value = errorText(e); }
		finally { if (version === selectionVersion) loadingThread.value = false; }
	}
	function refreshThread(id, version = selectionVersion, afterCurrent = false) {
		const existing = threadRequests.get(id);
		if (existing?.version === version) {
			existing.dirty ||= afterCurrent;
			return existing.promise;
		}
		const request = { version, dirty: false, promise: null };
		request.promise = (async () => {
			do {
				request.dirty = false;
				await fetchThread(id, version);
			} while (request.dirty && !dead && version === selectionVersion && selected.value?.id === id);
		})().finally(() => {
			if (threadRequests.get(id) === request) threadRequests.delete(id);
		});
		threadRequests.set(id, request);
		return request.promise;
	}

	async function fetchThread(id, version) {
		const thread = threadFor(id), known = new Set(thread.items.filter((m) => !m._status).map((m) => m.id));
		const near = nearBottom(), wasLoaded = thread.loaded;
		let cursor = null, first, fresh = [];
		// Catch up across as many pages as necessary, until existing history overlaps.
		do {
			const result = await call('messages', { conversation_id: id, cursor });
			if (dead || version !== selectionVersion || selected.value?.id !== id) return;
			first ||= result;
			fresh.push(...result.items);
			if (!wasLoaded || result.items.some((m) => known.has(m.id)) || !result.has_more) break;
			cursor = result.next_cursor;
		} while (cursor);
		if (dead || version !== selectionVersion) return;
		const added = fresh.some((m) => !known.has(m.id));
		const recoveredSend = thread.items.some((pending) => pending._status === 'failed' && fresh.some((saved) => saved.client_message_id === pending.client_message_id && saved.sender_role === pending.sender_role));
		thread.items = mergeMessages(thread.items, fresh);
		if (recoveredSend && !thread.items.some((m) => m._status === 'failed')) actionError.value = '';
		if (!wasLoaded) { thread.hasMore = first.has_more; thread.cursor = first.next_cursor; }
		thread.loaded = true;
		const { items, next_cursor, has_more, ...metadata } = first;
		selected.value = { ...selected.value, ...metadata, id };
		threadError.value = '';
		if (near) { await bottom(); void markVisible(); }
		else if (added) showNew.value = true;
	}
	async function older() {
		const id = selected.value.id, thread = threadFor(id), version = selectionVersion;
		if (thread.loadingOlder || !thread.hasMore) return;
		thread.loadingOlder = true; threadError.value = '';
		try {
			const result = await call('messages', { conversation_id: id, cursor: thread.cursor });
			if (dead || version !== selectionVersion) return;
			thread.items = mergeMessages(thread.items, result.items); thread.hasMore = result.has_more; thread.cursor = result.next_cursor;
			return true;
		} catch (e) { if (!dead && version === selectionVersion) threadError.value = errorText(e); }
		finally { thread.loadingOlder = false; }
	}
	async function markVisible(force = false) {
		if (!visible() || !nearBottom()) return;
		const id = selected.value?.id, message = latestSaved(active.value);
		if (!id || !message || message.id === lastRead || readInFlight) return;
		// Admin sends already advance the shared read state atomically in Supabase.
		if (!force && message.sender_role === 'admin') { lastRead = message.id; return; }
		readInFlight = message.id;
		try {
			await call('mark_read', { conversation_id: id, message_id: message.id });
			if (dead) return;
			if (selected.value?.id === id) lastRead = message.id;
			const row = inbox.value.find((c) => c.id === id);
			if (row) { totalUnread.value = Math.max(0, totalUnread.value - (row.unread_count || 0)); row.unread_count = 0; }
		} catch { /* Leave unread and retry on focus/scroll/catch-up. */ }
		finally {
			readInFlight = '';
			if (!dead && latestSaved(active.value)?.id !== message.id) {
				lastRead = '';
				void markVisible(true);
			}
		}
	}

	function newMessage(kind, body, file) {
		const clientId = clientMessageId();
		return { id: 'pending-' + clientId, client_message_id: clientId, conversation_id: selected.value.id,
			kind, body, sender_role: 'admin', sender_display_name: displayName.value, created_at: new Date().toISOString(),
			_status: 'sending', _file: file ? markRaw(file) : null, media_url: file ? URL.createObjectURL(file) : null };
	}
	async function send() {
		if (!maySend.value || !draft.value.trim() || [...draft.value].length > 4000) return;
		const message = newMessage('text', draft.value);
		draft.value = ''; threadFor(message.conversation_id).items = mergeMessages(active.value.items, [message]);
		await bottom(); await transmit(message);
	}
	async function upload(file) {
		if (!file || !maySend.value) return;
		if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 8388608) {
			actionError.value = 'Choose a JPEG, PNG, or WebP photo no larger than 8 MiB.'; return;
		}
		const message = newMessage('photo', null, file); photoObjectURLs.add(message.media_url);
		threadFor(message.conversation_id).items = mergeMessages(active.value.items, [message]);
		await bottom(); await transmit(message);
	}
	async function transmit(message) {
		if (dead || !canSend.value || offline.value || inFlightSends.has(message.client_message_id)) return;
		const thread = threadFor(message.conversation_id);
		inFlightSends.add(message.client_message_id);
		message._status = 'sending'; actionError.value = '';
		try {
			let saved;
			if (message.kind === 'photo') {
				sendingPhoto.value = true;
				const data = new FormData(); data.append('file', message._file);
				data.append('conversation_id', message.conversation_id); data.append('client_message_id', message.client_message_id);
				const response = await fetch('/api/method/' + API + 'send_photo', { method: 'POST', credentials: 'same-origin',
					headers: { 'X-Frappe-CSRF-Token': frappe.csrf_token }, body: data });
				const json = await response.json();
				if (!response.ok || json.exc || !json.message) throw new Error('Upload failed');
				saved = json.message;
			} else saved = await call('send_text', { conversation_id: message.conversation_id, client_message_id: message.client_message_id, body: message.body });
			if (dead) return;
			thread.items = mergeMessages(thread.items, [saved]);
			if (message.media_url?.startsWith('blob:')) { URL.revokeObjectURL(message.media_url); photoObjectURLs.delete(message.media_url); }
			if (selected.value?.id === message.conversation_id) {
				lastRead = saved.id;
				await bottom();
			}
			scheduleRefresh({ inbox: true });
		} catch {
			const pending = thread.items.find((m) => m.client_message_id === message.client_message_id && m._status);
			// A realtime echo may already have confirmed the commit before HTTP failed.
			if (pending) {
				pending._status = 'failed';
				if (!dead && selected.value?.id === message.conversation_id) actionError.value = 'Message could not be confirmed. Retry uses the same message ID.';
			}
		} finally { sendingPhoto.value = false; inFlightSends.delete(message.client_message_id); }
	}
	function back() { mobileThread.value = false; showNew.value = false; }

	function scheduleRefresh({ inbox: refreshInbox = true, thread: refreshOpenThread = false } = {}) {
		if (dead) return;
		inboxDirty ||= refreshInbox;
		threadDirty ||= refreshOpenThread;
		if (eventTimer) return;
		eventTimer = setTimeout(() => { eventTimer = null; void flushRefresh(); }, 160);
	}
	function flushRefresh() {
		if (dead || initializing || document.hidden) return;
		if (inboxDirty && !refreshingInbox) {
			inboxDirty = false; refreshingInbox = true;
			void loadInbox(false).finally(() => {
				refreshingInbox = false;
				if (!dead && inboxDirty) scheduleRefresh({ inbox: false });
			});
		}
		const id = selected.value?.id, version = selectionVersion;
		if (!id || !mobileThread.value) { threadDirty = false; return; }
		if (threadDirty) {
			threadDirty = false;
			void refreshThread(id, version, true).catch((error) => {
				if (!dead && version === selectionVersion) threadError.value = errorText(error);
			});
		}
	}
	function onRealtime(payload) {
		if (payload.event === 'bridge_heartbeat') {
			heartbeatAt = Date.now(); bridgeStatus.value = payload.status;
		} else if (payload.event === 'bridge_status') {
			heartbeatAt = Date.now();
			bridgeStatus.value = payload.status;
			if (payload.status === 'Live') scheduleRefresh({ thread: true });
		} else if (payload.event === 'read_updated') {
			if (payload.conversation_id === selected.value?.id && payload.message_id) lastRead = payload.message_id;
			scheduleRefresh({ inbox: true });
		} else if (['message_created', 'context_updated'].includes(payload.event)) {
			const current = payload.conversation_id === selected.value?.id;
			const alreadySaved = payload.message_id && active.value?.items.some((m) => m.id === payload.message_id && !m._status);
			scheduleRefresh({ thread: current && !alreadySaved });
		}
	}
	function configureSocket() {
		const socket = frappe.realtime.socket, manager = socket?.io;
		if (!manager?.opts || socket.connected) return;
		const site = frappe.boot?.sitename;
		let changed = false;
		if (site && manager.opts.extraHeaders?.['X-Frappe-Site-Name'] !== site) {
			manager.opts.extraHeaders = { ...manager.opts.extraHeaders, 'X-Frappe-Site-Name': site };
			changed = true;
		}
		const port = Number(frappe.boot?.socketio_port || window.socketio_port);
		if (frappe.boot?.developer_mode && location.protocol === 'http:' && location.port && Number.isInteger(port) && port > 0 && port < 65536) {
			const address = new URL(location.origin); address.port = String(port);
			if (new URL(manager.uri, location.origin).origin !== address.origin) {
				manager.uri = address.origin;
				Object.assign(manager.opts, { hostname: address.hostname, port: address.port, secure: false });
				changed = true;
			}
		}
		if (changed) manager.engine?.close();
	}
	function onConnect() {
		clearTimeout(socketTimer); socketTimer = null; socketAttempts = 0;
		socketConnected.value = true; scheduleRefresh({ thread: true }); void refreshHealth();
	}
	function scheduleSocketReconnect() {
		const socket = frappe.realtime.socket;
		if (dead || offline.value || document.hidden || socketTimer || !socket || socket.connected) return;
		socketTimer = setTimeout(() => {
			socketTimer = null;
			if (dead || offline.value || document.hidden) return;
			if (!frappe.realtime.socket?.connected) {
				frappe.realtime.socket?.connect?.();
				scheduleSocketReconnect();
			}
		}, Math.min(30000, 1000 * 2 ** Math.min(socketAttempts++, 5)));
	}
	function onDisconnect() { socketConnected.value = false; scheduleSocketReconnect(); }
	function refreshHealth() {
		if (healthRequest) return healthRequest;
		healthRequest = call('bootstrap').then((result) => {
			if (!dead) applyBootstrap(result);
		}).catch(() => { if (!dead) bridgeStatus.value = 'Offline'; }).finally(() => { healthRequest = null; });
		return healthRequest;
	}
	function applyBootstrap(result) {
		canSend.value = result.can_send; displayName.value = result.display_name;
		setupNotice.value = result.setup_notice || ''; bridgeStatus.value = result.health.status;
		heartbeatAt = Date.now();
	}
	function recover() {
		offline.value = !navigator.onLine;
		if (!document.hidden && !offline.value) {
			if (!frappe.realtime.socket?.connected) {
				configureSocket();
				frappe.realtime.socket?.connect?.();
				scheduleSocketReconnect();
			}
			void refreshHealth(); scheduleRefresh({ thread: true });
		}
	}

	async function openNotificationLink() {
		const options = frappe.route_options || {};
		const params = new URLSearchParams(window.location.search);
		const id = options.conversation || params.get('conversation');
		const eventId = options.homeall_event || params.get('homeall_event');
		if (!id || !/^[0-9a-f-]{36}$/i.test(id) || dead) return;
		await openConversation(inbox.value.find((c) => c.id === id) || { id });
		if (!dead && selected.value?.id === id && !threadError.value && eventId && /^[0-9a-f-]{36}$/i.test(eventId)) {
			void frappe.call({ method: 'homeall_ecommerce_integration.notifications.api.mark_opened', args: { event_id: eventId } });
		}
	}
	function routeChanged() {
		if (!initializing && frappe.get_route?.()[0] === 'chat') void openNotificationLink();
	}
	async function start() {
		if (started) return;
		started = true;
		initializing = true;
		dead = false;
		// A local health watchdog only; no inbox or message polling.
		healthTimer = setInterval(() => { if (Date.now() - heartbeatAt > 35000) bridgeStatus.value = 'Offline'; }, 5000);
		configureSocket();
		frappe.realtime.on('homeall_chat', onRealtime);
		stopRoutes = listenForRoutes(frappe.router, routeChanged, 'chat');
		frappe.realtime.socket?.on('connect', onConnect); frappe.realtime.socket?.on('disconnect', onDisconnect);
		frappe.realtime.socket?.on('connect_error', onDisconnect);
		socketConnected.value = !!frappe.realtime.socket?.connected;
		if (!socketConnected.value) scheduleSocketReconnect();
		document.addEventListener('visibilitychange', recover); window.addEventListener('focus', recover);
		window.addEventListener('online', recover); window.addEventListener('offline', recover);
		const initialization = call('bootstrap', { include_inbox: true });
		healthRequest = initialization;
		try {
			const result = await initialization;
			if (dead) return;
			applyBootstrap(result);
			if (result.inbox && !search.value && !unreadOnly.value) applyInbox(result.inbox);
			else await loadInbox();
			if (dead) return;
			await openNotificationLink();
		} catch { if (!dead) { inboxError.value = 'Chat access is unavailable. Check your permissions and server configuration.'; loadingInbox.value = false; bridgeStatus.value = 'Offline'; } }
		finally {
			initializing = false;
			if (healthRequest === initialization) healthRequest = null;
			if (!dead && (inboxDirty || threadDirty)) scheduleRefresh({ inbox: false });
		}
	}
	function stop() {
		dead = true; started = false; selectionVersion++; inboxVersion++;
		clearTimeout(searchTimer); clearTimeout(eventTimer); clearTimeout(socketTimer); clearInterval(healthTimer);
		frappe.realtime.off('homeall_chat', onRealtime);
		stopRoutes();
		frappe.realtime.socket?.off('connect', onConnect); frappe.realtime.socket?.off('disconnect', onDisconnect);
		frappe.realtime.socket?.off('connect_error', onDisconnect);
		document.removeEventListener('visibilitychange', recover); window.removeEventListener('focus', recover);
		window.removeEventListener('online', recover); window.removeEventListener('offline', recover);
		for (const url of photoObjectURLs) URL.revokeObjectURL(url);
		photoObjectURLs.clear();
		view = null;
	}
	onScopeDispose(stop);

	return {
		inbox, totalUnread, search, unreadOnly, selected, mobileThread,
		loadingInbox, loadingThread, inboxError, threadError, actionError, setupNotice,
		canSend, displayName, bridgeStatus, socketConnected, offline,
		inboxCursor, inboxMore, loadingMore, threads, drafts, showNew, sendingPhoto,
		active, draft, connection, pinned, snapshot, contextType, contextPrice,
		contextCurrency, orderTotal, orderSummary, maySend,
		loadInbox, moreInbox, openConversation, older,
		markVisible, send, upload, transmit, back, bottom, bindView, start,
	};
});
