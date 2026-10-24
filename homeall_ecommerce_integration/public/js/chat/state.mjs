export function normalizeMessage(message) {
	return { ...message, sender_display_name: typeof message.sender_display_name === 'string' ? message.sender_display_name : null };
}

export function staffDisplayName(message) {
	return typeof message.sender_display_name === 'string' ? message.sender_display_name.trim() || 'Support' : 'Support';
}

// Pure reconciliation shared by initial loads, catch-up, optimistic sends and echoes.
export function mergeMessages(current, incoming) {
	const result = [...current];
	for (const incomingMessage of incoming) {
		const message = normalizeMessage(incomingMessage);
		const index = result.findIndex((m) => m.id === message.id || (
			m.client_message_id && m.client_message_id === message.client_message_id &&
			m.conversation_id === message.conversation_id && m.sender_role === message.sender_role
		));
		if (index < 0) result.push(message);
		else if (!message._status || result[index]._status) {
			const previous = result[index];
			// A saved result replaces all optimistic state, including its guessed name.
			// Later legacy responses must not erase an already saved, immutable alias.
			result[index] = previous._status ? message : {
				...previous, ...message,
				sender_display_name: message.sender_display_name?.trim() ? message.sender_display_name : previous.sender_display_name ?? null,
			};
		}
	}
	return result.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));
}

export function sortConversations(items) {
	return [...new Map(items.map((item) => [item.id, item])).values()].sort((a, b) =>
		(b.last_message_at || '').localeCompare(a.last_message_at || '') || b.id.localeCompare(a.id));
}

export function isNearBottom(element) {
	return !element || element.scrollHeight - element.scrollTop - element.clientHeight < 100;
}

export function clientMessageId() {
	if (crypto.randomUUID) return crypto.randomUUID();
	// getRandomValues also works on HTTP development Desk origins.
	const bytes = crypto.getRandomValues(new Uint8Array(16));
	bytes[6] = (bytes[6] & 15) | 64;
	bytes[8] = (bytes[8] & 63) | 128;
	const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function safeImage(value) {
	if (typeof value !== 'string') return undefined;
	try {
		const url = new URL(value, window.location.origin);
		if (url.protocol === 'https:' || (url.origin === window.location.origin && url.protocol === 'http:')) return url.href;
	} catch { /* Invalid external snapshot image. */ }
	return undefined;
}
