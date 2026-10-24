const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function listenForRoutes(router, callback, namespace) {
	if (!router) return () => {};
	if (!router.jq && router.init) router.init();
	if (router.jq) {
		// This framework's EventEmitterMixin.off wraps a new function and cannot
		// remove the wrapper installed by on. A namespace guarantees real disposal.
		const event = 'change.homeall-' + namespace;
		router.jq.on(event, callback);
		return () => router.jq.off(event, callback);
	}
	router.on?.('change', callback);
	return () => router.off?.('change', callback);
}

export function destination(value, origin) {
	try {
		const url = new URL(value, origin);
		if (url.origin !== origin || url.hash) return null;
		const allowed = url.pathname === '/desk/online-order'
			? ['order', 'homeall_event'] : url.pathname === '/desk/chat'
				? ['conversation', 'message', 'homeall_event'] : [];
		if (!allowed.length || [...url.searchParams.keys()].some((key) => !allowed.includes(key))) return null;
		if (![...url.searchParams.values()].every((value) => uuid.test(value))) return null;
		if (!uuid.test(url.searchParams.get(allowed[0]) || '')) return null;
		return url;
	} catch { return null; }
}

export function mayPrompt({ enabled }) {
	// Unsupported/blocked browsers still get the setup instructions in the modal.
	// Permission is only requested after the user presses Enable.
	return !enabled;
}

export function notificationData(data, origin, now = Date.now()) {
	if (!data || !uuid.test(data.event_id || '') || !['order_created', 'chat_message'].includes(data.type)) return null;
	const url = destination(data.destination, origin);
	if (!url || url.searchParams.get('homeall_event') !== data.event_id) return null;
	if (Number(data.expires_at) * 1000 <= now || !Number.isFinite(Number(data.expires_at))) return null;
	return { url, title: data.type === 'order_created' ? 'New online order' : 'New customer message',
		body: 'Open Homeall to view the details.', tag: 'homeall-' + data.event_id };
}
