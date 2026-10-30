// Copyright (c) 2026, Tes Pheakdey and contributors
// For license information, please see license.txt

frappe.ui.form.on("App Open Ads", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0 || !frm.has_perm("write")) {
			return;
		}

		frm.add_custom_button(
			__("Publish to Supabase"),
			() => {
				if (frm.is_dirty()) {
					frappe.msgprint(__("Save your changes before publishing to Supabase."));
					return;
				}

				return run_supabase_action(
					frm,
					"publish_to_supabase",
					__("Publishing to Supabase..."),
					__("Ad published to Supabase")
				);
			},
			__("Action")
		);

		frm.add_custom_button(
			__("Unpublish to Supabase"),
			() =>
				run_supabase_action(
					frm,
					"unpublish_to_supabase",
					__("Unpublishing in Supabase..."),
					__("Ad set to draft in Supabase. ERP record kept.")
				),
			__("Action")
		);
	},
});

function run_supabase_action(frm, method, freeze_message, success_message) {
	return frappe
		.call({
			method: `homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_open_ads.app_open_ads.${method}`,
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message,
		})
		.then(({ message }) => {
			if (message?.success) {
				frappe.show_alert({ message: success_message, indicator: "green" });
			}
		});
}
