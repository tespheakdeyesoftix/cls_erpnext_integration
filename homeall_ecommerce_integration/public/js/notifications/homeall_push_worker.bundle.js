import { initializeApp } from 'firebase/app';
import { getMessaging, onBackgroundMessage } from 'firebase/messaging/sw';
import { destination, notificationData } from './policy.mjs';

// Register before Firebase, which also installs a notification click handler.
self.addEventListener('notificationclick', (event) => {
	const url = destination(event.notification.data?.url, self.location.origin);
	if (!url) return;
	event.stopImmediatePropagation();
	event.notification.close();
	event.waitUntil((async () => {
		const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
		const existing = windows.find((client) => {
			const current = new URL(client.url);
			return current.origin === url.origin && /^\/(desk|app)(\/|$)/.test(current.pathname);
		});
		if (existing) {
			const navigated = await existing.navigate(url.href);
			if (navigated) return navigated.focus();
		}
		return self.clients.openWindow(url.href);
	})());
});

// Firebase delivers data-only messages here only when no app window is visible.
const messaging = getMessaging(initializeApp(self.HOMEALL_FIREBASE_CONFIG));
onBackgroundMessage(messaging, async ({ data }) => {
	const notice = notificationData(data, self.location.origin);
	if (!notice) return;
	await self.registration.showNotification(notice.title, {
		body: notice.body, tag: notice.tag,
		icon: '/assets/homeall_ecommerce_integration/icons/dsku-notification-192.png',
		data: { url: notice.url.href },
	});
});
