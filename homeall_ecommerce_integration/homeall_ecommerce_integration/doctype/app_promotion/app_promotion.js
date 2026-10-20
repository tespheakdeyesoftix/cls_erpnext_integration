// Copyright (c) 2026, Tes Pheakdey and contributors
// For license information, please see license.txt

const PROMOTION_SERVICE =
	"homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.app_promotion_sync";

frappe.ui.form.on("App Promotion", {
	refresh(frm) {
		if (frm.doc.docstatus ==2 || !frm.has_perm("write")) {
			return;
		}
		

		frm.add_custom_button(
			__("Submit to App Database (Supabase)"),
			() =>
				run_promotion_action(
					frm,
					"submit_to_app_database",
					__("Submitting promotion..."),
					__("Promotion submitted to the App Database"),
					true
				),
			__("Sync to App")
		);

		if (!frm.doc.is_synced) {
			return;
		}

		frm.add_custom_button(
			__("Generate Promotion Pricing Rules"),
			() =>
				run_promotion_action(
					frm,
					"generate_promotion_pricing_rules",
					__("Generating promotion pricing rules..."),
					__("Promotion pricing rules generated")
				),
			__("Supabase")
		);

		frm.add_custom_button(
			__("Generate Notification to Customer / User"),
			() => {
				frappe.confirm(
					__(
						"Send this promotion notification now? Running this action again may notify customers more than once."
					),
					() =>
						run_promotion_action(
							frm,
							"notify_promotion_users",
							__("Sending promotion notifications..."),
							__("Promotion notifications generated")
						)
				);
			},
			__("Supabase")
		);
	},
});

function run_promotion_action(frm, method, freeze_message, success_message, reload = false) {
	return frappe
		.call({
			method: `${PROMOTION_SERVICE}.${method}`,
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message,
		})
		.then(async () => {
			if (reload) {
				await frm.reload_doc();
			}
			frappe.show_alert({ message: success_message, indicator: "green" });
		});
}
