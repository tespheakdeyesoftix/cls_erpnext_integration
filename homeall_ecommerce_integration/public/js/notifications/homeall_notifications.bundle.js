import { initializeApp, getApp } from 'firebase/app';
import { getMessaging, getToken, deleteToken, isSupported, onMessage } from 'firebase/messaging';
import { listenForRoutes, mayPrompt, notificationData } from './policy.mjs';

const API = 'homeall_ecommerce_integration.notifications.api.';
const call = (method, args = {}, type = 'POST') => frappe.call({ method: API + method, args, type }).then((r) => r.message);
const storage = {
	get(key) { try { return localStorage.getItem(key); } catch { return null; } },
	set(key, value) { try { localStorage.setItem(key, String(value)); } catch { /* Private storage may be unavailable. */ } },
};

async function start() {
	if (!frappe.session?.user || frappe.session.user === 'Guest' || window.homeallNotifications) return;
	const service = { preferences };
	window.homeallNotifications = service;
	let config, supported = false, messaging, busy = false, permissionDialog, dialogVisible = false;
	const userKey = 'homeall-push:' + frappe.session.user + ':';
	const installationKey = 'homeall-push-installation';
	let installation = storage.get(installationKey);
	const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
	const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
	const permission = () => 'Notification' in window ? Notification.permission : 'unsupported';
	const active = () => storage.get(userKey + 'enabled') === 'true' && permission() === 'granted';
	const seen = new Set();

	function promptUntilEnabled() {
		if (config?.enabled && config.push_enabled && !busy && !dialogVisible && mayPrompt({ enabled: active() })) preferences();
	}
	async function enable() {
		if (busy) return;
		if (!supported || !config?.configured || (ios && !standalone)) return preferences();
		// This call must happen synchronously inside the user's click, before any await.
		const requested = permission() === 'granted' ? Promise.resolve('granted') : Notification.requestPermission();
		busy = true;
		try {
			if (await requested !== 'granted') {
				storage.set(userKey + 'enabled', false);
				permissionDialog?.hide();
				preferences(); // Explain how to unblock permission; never repeat the native request automatically.
				return;
			}
			if (!installation) { installation = crypto.randomUUID(); storage.set(installationKey, installation); }
			const registration = await navigator.serviceWorker.register('/api/method/' + API + 'service_worker', { scope: '/homeall-push/' });
			let app;
			try { app = getApp('homeall-push'); } catch { app = initializeApp(config.firebase, 'homeall-push'); }
			if (!messaging) {
				messaging = getMessaging(app);
				onMessage(messaging, ({ data }) => {
					const notice = notificationData(data, location.origin);
					if (!notice || seen.has(data.event_id)) return;
					seen.add(data.event_id);
					if (seen.size > 200) seen.delete(seen.values().next().value);
					frappe.show_alert({ message: __(notice.title), indicator: 'blue' });
					// The native Frappe realtime event owns the bell count; push never increments it.
				});
			}
			const token = await getToken(messaging, { vapidKey: config.vapid_key, serviceWorkerRegistration: registration });
			if (!token) throw new Error('No Firebase registration');
			await call('register', { installation_id: installation, token });
			storage.set(userKey + 'enabled', true);
			storage.set(userKey + 'disabled', false);
			permissionDialog?.hide();
		} catch {
			storage.set(userKey + 'enabled', false);
			frappe.msgprint(__('Unable to enable browser notifications. Check the site configuration and try again.'));
		} finally { busy = false; }
	}
	async function disable() {
		if (busy) return;
		busy = true;
		try {
			await call('unregister', { installation_id: installation });
			storage.set(userKey + 'enabled', false);
			storage.set(userKey + 'disabled', true);
			if (messaging) await deleteToken(messaging);
			permissionDialog?.hide();
		} catch { frappe.msgprint(__('Unable to update notification preferences. Please retry.')); }
		finally { busy = false; }
	}
	function preferences() {
		if (dialogVisible) return;
		let text;
		if (!config?.push_enabled || !config?.configured) text = __('Browser notifications are not configured for this site.');
		else if (ios && !standalone) text = __('On iPhone or iPad, use Share → Add to Home Screen. Open Homeall from that icon, then enable notifications. Requires iOS/iPadOS 16.4 or later.');
		else if (!supported) text = __('This browser does not support notifications. Use a supported browser over HTTPS.');
		else if (permission() === 'denied') text = __('Notifications are blocked. Allow notifications for this site in your browser or phone settings, then try again.');
		else text = active() ? __('Browser notifications are enabled on this device.') : __('Receive alerts for new orders and customer chat messages, even when the ERPNext tab is closed.');
		permissionDialog = new frappe.ui.Dialog({
			title: __('Browser notifications'), fields: [{ fieldtype: 'HTML', options: '<p>' + text + '</p>' }],
			primary_action_label: active() ? __('Disable notifications') : __('Enable notifications'),
			primary_action: active() ? disable : enable,
			secondary_action_label: __('Later'), secondary_action: () => permissionDialog.hide(),
		});
		permissionDialog.onhide = () => { dialogVisible = false; };
		dialogVisible = true;
		permissionDialog.show();
		if (!config?.configured || !config?.push_enabled || !supported || (ios && !standalone) || permission() === 'denied') {
			permissionDialog.get_primary_btn().hide();
		}
	}
	try {
		config = await call('get_config', {}, 'GET');
		if (!config.enabled) return;
		// Remove the old standalone action if an earlier bundle inserted it.
		document.getElementById('homeall-notification-preferences')?.remove();
		frappe.realtime.on('homeall_notification_read', ({ unread_count }) => {
			const view = frappe.app?.sidebar?.notifications?.tabs?.notifications;
			if (view) {
				view.update_count_badge(unread_count);
				view.notifications_fetched = false;
			} else {
				frappe.boot.notification_unread_count = unread_count;
				document.querySelectorAll('.notification-count').forEach((badge) => {
					badge.textContent = unread_count > 99 ? '99+' : String(unread_count);
					badge.classList.toggle('hidden', !unread_count);
				});
			}
		});
		const manifest = document.createElement('link'); manifest.rel = 'manifest';
		manifest.href = '/assets/homeall_ecommerce_integration/notifications.webmanifest?v=dsku-1'; document.head.append(manifest);
		if (!document.querySelector('link[rel="apple-touch-icon"]')) {
			const touchIcon = document.createElement('link'); touchIcon.rel = 'apple-touch-icon';
			touchIcon.sizes = '180x180';
			touchIcon.href = '/assets/homeall_ecommerce_integration/icons/dsku-notification-180.png';
			document.head.append(touchIcon);
		}
		supported = window.isSecureContext && 'Notification' in window && 'serviceWorker' in navigator && await isSupported();
		if (!config.push_enabled) return;
		if (supported && config.configured && permission() === 'granted' && storage.get(userKey + 'disabled') !== 'true') await enable();
		promptUntilEnabled();
		// Later/close dismisses this visit only. The next Desk navigation or reload
		// asks again until the browser registration has actually succeeded.
		listenForRoutes(frappe.router, promptUntilEnabled, 'notification-opt-in');
		let lastRefresh = Date.now();
		document.addEventListener('visibilitychange', () => {
			if (!document.hidden && active() && Date.now() - lastRefresh > 3600000) {
				lastRefresh = Date.now(); void enable();
			}
		});
	} catch { /* Notification setup never prevents Desk from opening. */ }
}

$(start);
