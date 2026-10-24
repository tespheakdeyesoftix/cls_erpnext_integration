frappe.pages['chat'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: 'Chat', single_column: true });
	$(wrapper).addClass('homeall-chat-page');
	page.set_secondary_action(__('Refresh'), () => wrapper.chatApp?.refresh(), 'refresh', __('Refreshing…'));
	// Desk emits a wrapper hide event; it does not call an on_page_hide hook.
	$(wrapper).on('hide.homeall-chat', () => {
		wrapper.chatVisible = false;
		wrapper.chatApp?.destroy();
		wrapper.chatApp = null;
	});
};

frappe.pages['chat'].on_page_show = async function (wrapper) {
	wrapper.chatVisible = true;
	await frappe.require(['chat.bundle.js', 'chat.bundle.css']);
	if (!wrapper.chatVisible || wrapper.chatApp) return;
	const mount = $(wrapper).find('.layout-main-section').empty();
	wrapper.chatApp = new frappe.ui.HomeallChatPage({ wrapper: mount });
};
