import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	create_custom_fields(
		{
			"Address": [
				{
					"fieldname": "custom_supabase_id",
					"label": "Supabase ID",
					"fieldtype": "Data",
					"insert_after": "custom_integration",
					"length": 36,
					"unique": 1,
					"read_only": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_recipient_name",
					"label": "Recipient Name",
					"fieldtype": "Data",
					"insert_after": "custom_supabase_id",
					"length": 150,
				},
				{
					"fieldname": "custom_commune_code",
					"label": "Commune Code",
					"fieldtype": "Link",
					"options": "Territory",
					"insert_after": "custom_district_code",
				},
				{
					"fieldname": "custom_village_code",
					"label": "Village Code",
					"fieldtype": "Link",
					"options": "Territory",
					"insert_after": "custom_commune_code",
				},
				{
					"fieldname": "custom_price_list_id",
					"label": "Price List ID",
					"fieldtype": "Data",
					"insert_after": "custom_price_list",
					"read_only": 1,
				},
			]
		},
		update=True,
	)

	old_field = "custom_commune_code_"
	new_field = "custom_commune_code"
	columns = frappe.db.get_table_columns("Address")
	if old_field in columns and new_field in columns:
		frappe.db.sql(
			f"""UPDATE `tabAddress`
			SET `{new_field}` = COALESCE(NULLIF(`{new_field}`, ''), `{old_field}`)
			WHERE IFNULL(`{old_field}`, '') != ''"""
		)

	old_custom_field = frappe.db.get_value(
		"Custom Field", {"dt": "Address", "fieldname": old_field}, "name"
	)
	if old_custom_field:
		frappe.delete_doc("Custom Field", old_custom_field, force=True, ignore_permissions=True)

	field_order_setter = frappe.db.get_value(
		"Property Setter",
		{"doc_type": "Address", "field_name": ["is", "not set"], "property": "field_order"},
		["name", "value"],
		as_dict=True,
	)
	if field_order_setter:
		field_order = json.loads(field_order_setter.value)
		field_order = [new_field if fieldname == old_field else fieldname for fieldname in field_order]
		frappe.db.set_value(
			"Property Setter",
			field_order_setter.name,
			"value",
			json.dumps(field_order),
			update_modified=False,
		)

	for fieldname in ("address_line1", "address_line2"):
		frappe.db.delete(
			"Property Setter",
			{"doc_type": "Address", "field_name": fieldname, "property": "length"},
		)
		make_property_setter("Address", fieldname, "length", 300, "Int")

	frappe.clear_cache(doctype="Address")
