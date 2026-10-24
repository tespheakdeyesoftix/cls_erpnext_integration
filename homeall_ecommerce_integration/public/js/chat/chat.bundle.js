import { createApp } from 'vue';
import { createPinia } from 'pinia';
import { routerKey } from 'vue-router';
import App from './App.vue';

frappe.provide('frappe.ui');
frappe.ui.HomeallChatPage = class {
	constructor({ wrapper }) {
		this.pinia = createPinia();
		this.app = createApp(App);
		this.app.use(this.pinia);
		// Frappe UI Buttons expect Vue Router injection; navigation remains owned by Desk.
		this.app.provide(routerKey, { push: (route) => frappe.set_route(route) });
		this.component = this.app.mount(wrapper.get ? wrapper.get(0) : wrapper);
	}
	refresh() {
		return this.component?.refresh();
	}
	destroy() {
		this.app?.unmount();
		this.component = null;
		this.app = null;
		this.pinia = null;
	}
};
