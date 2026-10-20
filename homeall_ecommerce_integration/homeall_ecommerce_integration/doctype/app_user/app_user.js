// Copyright (c) 2026, Tes Pheakdey and contributors
// For license information, please see license.txt

frappe.ui.form.on("App User", {
	refresh(frm) {
		load_user_addresses(frm);

		if (frm.is_new() || !frm.has_perm("write")) {
			return;
		}

		frm.add_custom_button(__("Reset Password"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Reset Password"),
				fields: [
					{
						fieldname: "password",
						fieldtype: "Password",
						label: __("New Password"),
						reqd: 1,
					},
					{
						fieldname: "confirm_password",
						fieldtype: "Password",
						label: __("Confirm New Password"),
						reqd: 1,
					},
				],
				primary_action_label: __("Reset Password"),
				primary_action(values) {
					if (values.password !== values.confirm_password) {
						frappe.msgprint(__("The passwords do not match."));
						return;
					}

					frappe.call({
						method:
							"homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_user.app_user.reset_app_user_password",
						args: {
							name: frm.doc.name,
							password: values.password,
						},
						freeze: true,
						freeze_message: __("Resetting password..."),
						callback() {
							dialog.hide();
							frappe.show_alert({
								message: __("Password reset successfully"),
								indicator: "green",
							});
						},
					});
				},
			});
			dialog.show();
		}, __("Actions"));

		const is_active = frm.doc.status !== "Inactive";
		const action_label = is_active ? __("Disable User") : __("Enable User");
		frm.add_custom_button(action_label, () => {
			const target_status = is_active ? __("Inactive") : __("Active");
			frappe.confirm(
				__("Set this user account to {0}?", [target_status]),
				() => {
					frappe.call({
						method:
							"homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_user.app_user.set_app_user_enabled",
						args: {
							name: frm.doc.name,
							enabled: is_active ? 0 : 1,
						},
						freeze: true,
						freeze_message: __("Updating account status..."),
						callback: async () => {
							await frm.reload_doc();
							frappe.show_alert({
								message: __("User account is now {0}", [target_status]),
								indicator: is_active ? "orange" : "green",
							});
						},
					});
				}
			);
		}, __("Actions"));
	},
});

const ADDRESS_METHOD =
	"homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_user.app_user_address";

function escape_html(value) {
	return frappe.utils.escape_html(String(value || ""));
}

function load_user_addresses(frm) {
	const field = frm.get_field("html_user_addresses");
	if (!field) {
		return;
	}

	if (frm.is_new()) {
		field.$wrapper.html(
			`<div class="text-muted">${__("Save the App User before adding addresses.")}</div>`
		);
		return;
	}

	field.$wrapper.html(`<div class="text-muted">${__("Loading addresses...")}</div>`);
	frappe
		.call({
			method: `${ADDRESS_METHOD}.get_user_addresses`,
			args: { app_user: frm.doc.name },
		})
		.then((response) => {
			render_user_addresses(frm, response.message?.addresses || []);
		});
}

function render_user_addresses(frm, addresses) {
	const field = frm.get_field("html_user_addresses");
	if (!field) {
		return;
	}

	frm.__user_addresses = new Map(addresses.map((address) => [address.name, address]));
	const can_write = frm.has_perm("write");
	const add_button = can_write
		? `<button class="btn btn-sm btn-primary app-user-address-add">${__("Add Address")}</button>`
		: "";
	const cards = addresses.length
		? addresses.map((address) => render_address_card(address, can_write)).join("")
		: `<div class="text-muted py-4">${__("No delivery addresses have been added.")}</div>`;

	field.$wrapper.html(`
		<div class="app-user-address-list">
			<div class="d-flex justify-content-between align-items-center mb-3">
				<h5 class="mb-0">${__("Delivery Addresses")}</h5>
				${add_button}
			</div>
			<div class="row">${cards}</div>
		</div>
	`);

	field.$wrapper.off(".app-user-addresses");
	field.$wrapper.on("click.app-user-addresses", ".app-user-address-add", () => {
		show_address_dialog(frm);
	});
	field.$wrapper.on("click.app-user-addresses", ".app-user-address-edit", (event) => {
		const address = frm.__user_addresses.get($(event.currentTarget).data("address-name"));
		if (address) {
			show_address_dialog(frm, address);
		}
	});
	field.$wrapper.on("click.app-user-addresses", ".app-user-address-delete", (event) => {
		const address_name = $(event.currentTarget).data("address-name");
		const address = frm.__user_addresses.get(address_name);
		if (address) {
			delete_user_address(frm, address);
		}
	});
}

function render_address_card(address, can_write) {
	const default_badge = address.is_default
		? `<span class="indicator-pill green ml-2">${__("Default")}</span>`
		: "";
	const actions = can_write
		? `<div class="mt-3">
			<button class="btn btn-xs btn-default app-user-address-edit" data-address-name="${escape_html(address.name)}">${__("Edit")}</button>
			<button class="btn btn-xs btn-danger app-user-address-delete ml-1" data-address-name="${escape_html(address.name)}">${__("Delete")}</button>
		</div>`
		: "";
	const recipient = [address.recipient_name, address.phone].filter(Boolean).join(" · ");

	return `
		<div class="col-md-6 mb-3">
			<div class="border rounded p-3 h-100">
				<div class="d-flex align-items-center mb-2">
					<strong>${escape_html(address.label)}</strong>${default_badge}
				</div>
				<div>${escape_html(recipient)}</div>
				<div class="text-muted mt-1">${escape_html(address.display_address)}</div>
				${actions}
			</div>
		</div>
	`;
}

function address_dialog_fields(dialog) {
	return [
		{ fieldname: "label", fieldtype: "Data", label: __("Label"), reqd: 1 },
		{ fieldtype: "Column Break" },
		{
			fieldname: "recipient_name",
			fieldtype: "Data",
			label: __("Recipient Name"),
			reqd: 1,
		},
		{ fieldtype: "Column Break" },
		{ fieldname: "phone", fieldtype: "Data", label: __("Phone"), reqd: 1 },
		{ fieldname: "address_section", fieldtype: "Section Break", label: __("Address") },
		{
			fieldname: "address_line1",
			fieldtype: "Data",
			label: __("Address Line 1"),
			reqd: 1,
		},
		{ fieldtype: "Column Break" },
		{ fieldname: "address_line2", fieldtype: "Data", label: __("Address Line 2") },
		{ fieldtype: "Column Break" },
		{ fieldname: "street", fieldtype: "Data", label: __("Street") },
		{ fieldname: "address_location_section", fieldtype: "Section Break" },
		{ fieldname: "city", fieldtype: "Data", label: __("City/Town"), reqd: 1 },
		{ fieldname: "postal_code", fieldtype: "Data", label: __("Postal Code") },
		{ fieldtype: "Column Break" },
		{
			fieldname: "country",
			fieldtype: "Link",
			options: "Country",
			label: __("Country"),
			default: "Cambodia",
			reqd: 1,
		},
		{ fieldtype: "Column Break" },
		{
			fieldname: "price_list",
			fieldtype: "Link",
			options: "Price List",
			label: __("Price List"),
			reqd: 1,
			get_query: () => ({
				filters: {
					selling: 1,
					custom_supabase_id: ["is", "set"],
				},
			}),
		},
		{ fieldname: "is_default", fieldtype: "Check", label: __("Default Delivery Address") },
		{
			fieldname: "administrative_section",
			fieldtype: "Section Break",
			label: __("Administrative Location"),
			collapsible: 1,
		},
		{
			fieldname: "province_code",
			fieldtype: "Link",
			options: "Territory",
			label: __("Province"),
			get_query: () => ({
				filters: { parent_territory: dialog.get_value("country") || "Cambodia" },
			}),
			onchange: () => {
				dialog.set_value("district_code", null);
				dialog.set_value("commune_code", null);
				dialog.set_value("village_code", null);
			},
		},
		{ fieldtype: "Column Break" },
		{
			fieldname: "district_code",
			fieldtype: "Link",
			options: "Territory",
			label: __("District"),
			get_query: () => ({ filters: { parent_territory: dialog.get_value("province_code") } }),
			onchange: () => {
				dialog.set_value("commune_code", null);
				dialog.set_value("village_code", null);
			},
		},
		{ fieldtype: "Column Break" },
		{
			fieldname: "commune_code",
			fieldtype: "Link",
			options: "Territory",
			label: __("Commune"),
			get_query: () => ({ filters: { parent_territory: dialog.get_value("district_code") } }),
			onchange: () => dialog.set_value("village_code", null),
		},
		{
			fieldname: "village_code",
			fieldtype: "Link",
			options: "Territory",
			label: __("Village"),
			get_query: () => ({ filters: { parent_territory: dialog.get_value("commune_code") } }),
		},
		{
			fieldname: "delivery_section",
			fieldtype: "Section Break",
			label: __("Delivery Details"),
			collapsible: 1,
		},
		{ fieldname: "formatted_address", fieldtype: "Small Text", label: __("Formatted Address") },
		{ fieldtype: "Column Break" },
		{ fieldname: "landmark", fieldtype: "Small Text", label: __("Landmark") },
		{ fieldtype: "Column Break" },
		{ fieldname: "delivery_note", fieldtype: "Small Text", label: __("Delivery Note") },
		{
			fieldname: "map_section",
			fieldtype: "Section Break",
			label: __("Map Details"),
			collapsible: 1,
		},
		{ fieldname: "latitude", fieldtype: "Float", label: __("Latitude"), precision: 6 },
		{ fieldtype: "Column Break" },
		{ fieldname: "longitude", fieldtype: "Float", label: __("Longitude"), precision: 6 },
		{ fieldtype: "Column Break" },
		{ fieldname: "google_place_id", fieldtype: "Data", label: __("Google Place ID") },
	];
}

function show_address_dialog(frm, address = null) {
	let dialog;
	dialog = new frappe.ui.Dialog({
		title: address ? __("Edit Address") : __("Add Address"),
		fields: address_dialog_fields({
			get_value(fieldname) {
				return dialog?.get_value(fieldname);
			},
			set_value(fieldname, value) {
				return dialog?.set_value(fieldname, value);
			},
		}),
		size: "large",
		primary_action_label: address ? __("Save Changes") : __("Add Address"),
		primary_action(values) {
			frappe.call({
				method: `${ADDRESS_METHOD}.save_user_address`,
				args: {
					app_user: frm.doc.name,
					address_name: address?.name || null,
					values,
				},
				freeze: true,
				freeze_message: __("Saving address..."),
				callback(response) {
					dialog.hide();
					render_user_addresses(frm, response.message?.addresses || []);
					frappe.show_alert({ message: __("Address saved"), indicator: "green" });
				},
			});
		},
	});

	if (address) {
		dialog.set_values(address);
	}
	dialog.show();
}

function delete_user_address(frm, address) {
	frappe.confirm(
		__("Delete address {0}?", [`<strong>${escape_html(address.label)}</strong>`]),
		() => {
			frappe.call({
				method: `${ADDRESS_METHOD}.delete_user_address`,
				args: { app_user: frm.doc.name, address_name: address.name },
				freeze: true,
				freeze_message: __("Deleting address..."),
				callback(response) {
					render_user_addresses(frm, response.message?.addresses || []);
					frappe.show_alert({ message: __("Address deleted"), indicator: "green" });
				},
			});
		}
	);
}
