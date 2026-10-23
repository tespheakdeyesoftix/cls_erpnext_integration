frappe.pages['chat'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Chat',
		single_column: true
	});
}