frappe.pages["online-order"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "ការបញ្ជាទិញអនឡាញ",
		single_column: true,
	});
};

frappe.pages["online-order"].on_page_show = function (wrapper) {
	const $mount = $(wrapper).find(".layout-main-section");
	$mount.empty();

	frappe
		.require(["online_order.bundle.js", "online_order.bundle.css"])
		.then(() => {
			wrapper.onlineOrderApp?.destroy();
			wrapper.onlineOrderApp = new frappe.ui.OnlineOrderPage({
				wrapper: $mount,
			});
		});
};

frappe.pages["online-order"].on_page_hide = function (wrapper) {
	wrapper.onlineOrderApp?.destroy();
	wrapper.onlineOrderApp = null;
};