import { createApp } from "vue";
import App from "./App.vue";
// Ship page and dialog styles with the JavaScript so they cannot load separately.
import "./online_order.bundle.css";

class OnlineOrderPage {
	constructor({ wrapper }) {
		this.wrapper = wrapper;
		this.app = null;
		this.mount();
	}

	mount() {
		this.app = createApp(App);
		this.app.config.globalProperties.frappe = window.frappe;
		this.app.config.globalProperties.__ = window.__;
		this.app.mount(this.wrapper.get ? this.wrapper.get(0) : this.wrapper);
	}

	destroy() {
		this.app?.unmount();
		this.app = null;
	}
}

frappe.provide("frappe.ui");
frappe.ui.OnlineOrderPage = OnlineOrderPage;

export default OnlineOrderPage;
