# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

from __future__ import annotations

import math
from datetime import timezone
from typing import Any
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import cint, get_datetime

from homeall_ecommerce_integration.controller import is_valid_uuid
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync import init_supabase


APP_USER_DOCTYPE = "App User"
ADDRESS_DOCTYPE = "Address"
ADDRESS_TABLE = "user_addresses"
ADMINISTRATIVE_LOCATION_TABLE = "administrative_locations"

STRING_LIMITS = {
	"label": 60,
	"recipient_name": 150,
	"phone": 50,
	"address_line1": 300,
	"address_line2": 300,
	"city": 100,
	"postal_code": 20,
}

ALLOWED_VALUE_FIELDS = {
	"label",
	"recipient_name",
	"phone",
	"address_line1",
	"address_line2",
	"city",
	"postal_code",
	"country",
	"latitude",
	"longitude",
	"google_place_id",
	"formatted_address",
	"street",
	"province_code",
	"district_code",
	"commune_code",
	"village_code",
	"landmark",
	"delivery_note",
	"price_list",
	"is_default",
}


def _log_error(title: str, operation: str, error: Exception) -> None:
	message = f"Operation: {operation}\nException type: {type(error).__name__}"
	if error_code := getattr(error, "code", None):
		message += f"\nSupabase error code: {error_code}"
	frappe.log_error(title=title, message=message)


def _parse_values(values: dict | str | None) -> frappe._dict:
	if isinstance(values, str):
		values = frappe.parse_json(values)
	if not isinstance(values, dict):
		frappe.throw(_("Address values must be an object."), exc=frappe.ValidationError)

	unknown_fields = set(values) - ALLOWED_VALUE_FIELDS
	if unknown_fields:
		frappe.throw(_("The address contains unsupported fields."), exc=frappe.ValidationError)

	return frappe._dict(values)


def _clean_text(value: Any) -> str | None:
	value = str(value or "").strip()
	return value or None


def _validate_text(values: frappe._dict) -> None:
	for fieldname, limit in STRING_LIMITS.items():
		value = _clean_text(values.get(fieldname))
		values[fieldname] = value
		if fieldname in {"label", "recipient_name", "phone", "address_line1", "city"} and not value:
			frappe.throw(
				_("{0} is required.").format(frappe.bold(fieldname.replace("_", " ").title())),
				exc=frappe.MandatoryError,
			)
		if value and len(value) > limit:
			frappe.throw(
				_("{0} cannot exceed {1} characters.").format(
					frappe.bold(fieldname.replace("_", " ").title()), limit
				),
				exc=frappe.ValidationError,
			)

	for fieldname in ALLOWED_VALUE_FIELDS - set(STRING_LIMITS) - {
		"latitude",
		"longitude",
		"is_default",
	}:
		values[fieldname] = _clean_text(values.get(fieldname))

	values.country = values.country or "Cambodia"
	if not frappe.db.exists("Country", values.country):
		frappe.throw(_("Country {0} does not exist.").format(frappe.bold(values.country)))
	if not values.price_list:
		frappe.throw(_("Price List is required."), exc=frappe.MandatoryError)

	values.is_default = cint(values.is_default)
	values.latitude = _parse_coordinate(values.latitude, "Latitude", -90, 90)
	values.longitude = _parse_coordinate(values.longitude, "Longitude", -180, 180)


def _parse_coordinate(value: Any, label: str, minimum: float, maximum: float) -> float | None:
	if value in (None, ""):
		return None
	try:
		value = float(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be a number.").format(label))
	if not math.isfinite(value) or value < minimum or value > maximum:
		frappe.throw(_("{0} must be between {1} and {2}.").format(label, minimum, maximum))
	return value


def _get_app_user(app_user: str, permission_type: str) -> Any:
	if not is_valid_uuid(app_user):
		frappe.throw(_("App User must have a valid Supabase UUID."), exc=frappe.ValidationError)
	doc = frappe.get_doc(APP_USER_DOCTYPE, app_user)
	doc.check_permission(permission_type)
	return doc


def _check_address_permission(permission_type: str) -> None:
	if not frappe.has_permission(ADDRESS_DOCTYPE, permission_type):
		frappe.throw(
			_("You do not have permission to {0} Address records.").format(permission_type),
			exc=frappe.PermissionError,
		)


def _get_linked_address_names(app_user: str) -> list[str]:
	return frappe.get_all(
		"Dynamic Link",
		filters={
			"parenttype": ADDRESS_DOCTYPE,
			"parentfield": "links",
			"link_doctype": APP_USER_DOCTYPE,
			"link_name": app_user,
		},
		pluck="parent",
	)


def _get_linked_addresses(app_user: str) -> list[Any]:
	addresses = [frappe.get_doc(ADDRESS_DOCTYPE, name) for name in _get_linked_address_names(app_user)]
	return sorted(
		addresses,
		key=lambda address: (cint(address.is_shipping_address), address.modified or address.creation),
		reverse=True,
	)


def _get_owned_address(app_user: str, address_name: str, permission_type: str) -> Any:
	address = frappe.get_doc(ADDRESS_DOCTYPE, address_name)
	address.check_permission(permission_type)
	if not address.has_link(APP_USER_DOCTYPE, app_user):
		frappe.throw(_("This Address does not belong to the selected App User."), exc=frappe.PermissionError)
	return address


def _get_territory(code: str | None, label: str) -> frappe._dict | None:
	if not code:
		return None
	territory = frappe.db.get_value(
		"Territory",
		code,
		["name", "territory_name", "parent_territory"],
		as_dict=True,
	)
	if not territory:
		frappe.throw(_("{0} Territory does not exist.").format(label))
	return territory


def _get_location_values(values: frappe._dict) -> dict:
	province = _get_territory(values.province_code, _("Province"))
	district = _get_territory(values.district_code, _("District"))
	commune = _get_territory(values.commune_code, _("Commune"))
	village = _get_territory(values.village_code, _("Village"))

	for child, parent, label in (
		(district, province, _("District")),
		(commune, district, _("Commune")),
		(village, commune, _("Village")),
	):
		if child and not parent:
			frappe.throw(_("Select the parent location before selecting {0}.").format(label))
		if child and child.parent_territory != parent.name:
			frappe.throw(_("The selected {0} is outside its parent location.").format(label))

	return {
		"province": province,
		"district": district,
		"commune": commune,
		"village": village,
	}


def _get_country_code(country: str) -> str:
	code = _clean_text(frappe.db.get_value("Country", country, "code"))
	if not code or len(code) != 2:
		frappe.throw(_("Country {0} must have a two-letter ISO code.").format(frappe.bold(country)))
	return code.upper()


def _get_price_list_id(price_list: str | None) -> str | None:
	if not price_list:
		return None
	price_list_values = frappe.db.get_value(
		"Price List", price_list, ["custom_supabase_id", "selling"], as_dict=True
	)
	if not price_list_values or not cint(price_list_values.selling):
		frappe.throw(
			_("Price List {0} must be enabled for selling.").format(frappe.bold(price_list))
		)
	price_list_id = price_list_values.custom_supabase_id
	if not is_valid_uuid(price_list_id):
		frappe.throw(
			_("Price List {0} must have a valid Supabase ID.").format(frappe.bold(price_list))
		)
	return str(price_list_id)


def _validate_remote_village(supabase, village_code: str | None) -> None:
	if not village_code:
		return
	try:
		response = (
			supabase.table(ADMINISTRATIVE_LOCATION_TABLE)
			.select("code")
			.eq("code", village_code)
			.limit(2)
			.execute()
		)
	except Exception as error:
		_log_error("Supabase Address Validation Error", "validate village code", error)
		frappe.throw(_("Could not validate the village code in Supabase. Please try again."))
	rows = response.data or []
	if len(rows) != 1 or str(rows[0].get("code")) != village_code:
		frappe.throw(_("The selected village does not exist in Supabase."))


def _apply_values(
	address: Any, values: frappe._dict, locations: dict, price_list_id: str
) -> None:
	province = locations["province"]
	district = locations["district"]
	address.update(
		{
			"address_title": values.label,
			"address_type": "Shipping",
			"custom_recipient_name": values.recipient_name,
			"phone": values.phone,
			"address_line1": values.address_line1,
			"address_line2": values.address_line2,
			"city": values.city,
			"state": province.territory_name if province else address.state,
			"county": district.territory_name if district else address.county,
			"pincode": values.postal_code,
			"country": values.country,
			"custom_latitude": values.latitude,
			"custom_longitude": values.longitude,
			"custom_google_place_id": values.google_place_id,
			"custom_formatted_address": values.formatted_address,
			"custom_street": values.street,
			"custom_province_code": values.province_code,
			"custom_district_code": values.district_code,
			"custom_commune_code": values.commune_code,
			"custom_village_code": values.village_code,
			"custom_landmark": values.landmark,
			"custom_delivery_note": values.delivery_note,
			"custom_price_list": values.price_list,
			"custom_price_list_id": price_list_id,
			"is_shipping_address": values.is_default,
			"disabled": 0,
		}
	)


def _format_timestamp(value: Any) -> str | None:
	if not value:
		return None
	return get_datetime(value).replace(tzinfo=timezone.utc).isoformat()


def _territory_name(code: str | None) -> str | None:
	return frappe.db.get_value("Territory", code, "territory_name") if code else None


def _address_payload(address: Any, app_user: str) -> dict | None:
	if not is_valid_uuid(address.custom_supabase_id):
		return None
	return {
		"id": str(address.custom_supabase_id),
		"user_id": app_user,
		"label": address.address_title,
		"recipient_name": address.custom_recipient_name,
		"phone": address.phone,
		"address_line1": address.address_line1,
		"address_line2": address.address_line2,
		"city": address.city,
		"state_province": _territory_name(address.custom_province_code) or address.state,
		"postal_code": address.pincode,
		"country_code": _get_country_code(address.country),
		"latitude": address.custom_latitude,
		"longitude": address.custom_longitude,
		"google_place_id": address.custom_google_place_id,
		"formatted_address": address.custom_formatted_address,
		"street": address.custom_street,
		"village": _territory_name(address.custom_village_code),
		"commune": _territory_name(address.custom_commune_code),
		"district": _territory_name(address.custom_district_code) or address.county,
		"village_code": address.custom_village_code,
		"landmark": address.custom_landmark,
		"delivery_note": address.custom_delivery_note,
		"price_list_id": address.custom_price_list_id,
		"is_default": bool(cint(address.is_shipping_address)),
		"created_at": _format_timestamp(address.creation),
		"updated_at": _format_timestamp(address.modified),
	}


def _snapshot(addresses: list[Any], app_user: str) -> dict[str, dict]:
	payloads = {}
	for address in addresses:
		if payload := _address_payload(address, app_user):
			payloads[payload["id"]] = payload
	return payloads


def _validate_rows(response, expected_ids: set[str], operation: str) -> None:
	rows = response.data or []
	returned_ids = {str(row.get("id")) for row in rows}
	if returned_ids != expected_ids:
		raise ValueError(f"Supabase {operation} did not return the expected address rows")


def _apply_remote_snapshot(supabase, before: dict[str, dict], after: dict[str, dict], app_user: str) -> None:
	removed_ids = set(before) - set(after)
	new_ids = set(after) - set(before)
	existing_ids = set(after) & set(before)

	for address_id in removed_ids:
		response = (
			supabase.table(ADDRESS_TABLE)
			.delete()
			.eq("id", address_id)
			.eq("user_id", app_user)
			.execute()
		)
		_validate_rows(response, {address_id}, "address delete")

	if new_ids:
		response = supabase.table(ADDRESS_TABLE).insert([after[address_id] for address_id in new_ids]).execute()
		_validate_rows(response, new_ids, "address insert")

	if existing_ids:
		response = (
			supabase.table(ADDRESS_TABLE)
			.upsert([after[address_id] for address_id in existing_ids], on_conflict="id")
			.execute()
		)
		_validate_rows(response, existing_ids, "address update")


def _restore_remote_snapshot(supabase, before: dict[str, dict], after: dict[str, dict], app_user: str) -> None:
	try:
		added_ids = set(after) - set(before)
		for address_id in added_ids:
			(
				supabase.table(ADDRESS_TABLE)
				.delete()
				.eq("id", address_id)
				.eq("user_id", app_user)
				.execute()
			)
		if before:
			supabase.table(ADDRESS_TABLE).upsert(list(before.values()), on_conflict="id").execute()
	except Exception as error:
		_log_error("Supabase Address Rollback Compensation Error", "restore address snapshot", error)


def _sync_remote(supabase, before: dict[str, dict], after: dict[str, dict], app_user: str) -> None:
	try:
		_apply_remote_snapshot(supabase, before, after, app_user)
	except Exception as error:
		_log_error("Supabase Address Sync Error", "synchronize user addresses", error)
		_restore_remote_snapshot(supabase, before, after, app_user)
		frappe.throw(_("Could not synchronize the user address with Supabase. Please try again."))

	frappe.db.after_rollback.add(
		lambda supabase=supabase, before=before, after=after, app_user=app_user: (
			_restore_remote_snapshot(supabase, before, after, app_user)
		)
	)


def _serialize_address(address: Any) -> dict:
	parts = [
		address.address_line1,
		address.address_line2,
		address.city,
		address.county,
		address.state,
		address.country,
	]
	return {
		"name": address.name,
		"supabase_id": address.custom_supabase_id,
		"label": address.address_title,
		"recipient_name": address.custom_recipient_name,
		"phone": address.phone,
		"address_line1": address.address_line1,
		"address_line2": address.address_line2,
		"city": address.city,
		"postal_code": address.pincode,
		"country": address.country,
		"latitude": address.custom_latitude,
		"longitude": address.custom_longitude,
		"google_place_id": address.custom_google_place_id,
		"formatted_address": address.custom_formatted_address,
		"display_address": address.custom_formatted_address or ", ".join(part for part in parts if part),
		"street": address.custom_street,
		"province_code": address.custom_province_code,
		"district_code": address.custom_district_code,
		"commune_code": address.custom_commune_code,
		"village_code": address.custom_village_code,
		"landmark": address.custom_landmark,
		"delivery_note": address.custom_delivery_note,
		"price_list": address.custom_price_list,
		"is_default": bool(cint(address.is_shipping_address)),
	}


def _serialized_addresses(app_user: str) -> list[dict]:
	return [_serialize_address(address) for address in _get_linked_addresses(app_user)]


@frappe.whitelist()
def get_user_addresses(app_user: str) -> dict:
	_get_app_user(app_user, "read")
	_check_address_permission("read")
	return {"addresses": _serialized_addresses(app_user)}


@frappe.whitelist()
def save_user_address(app_user: str, values: dict | str, address_name: str | None = None) -> dict:
	_get_app_user(app_user, "write")
	values = _parse_values(values)
	_validate_text(values)
	locations = _get_location_values(values)
	price_list_id = _get_price_list_id(values.price_list)

	if address_name:
		address = _get_owned_address(app_user, address_name, "write")
	else:
		_check_address_permission("create")
		address = frappe.new_doc(ADDRESS_DOCTYPE)
		address.custom_supabase_id = str(uuid4())
		address.append("links", {"link_doctype": APP_USER_DOCTYPE, "link_name": app_user})
		if not _get_linked_address_names(app_user):
			values.is_default = 1

	before_addresses = _get_linked_addresses(app_user)
	before = _snapshot(before_addresses, app_user)
	supabase = init_supabase()
	_validate_remote_village(supabase, values.village_code)
	if address_name and cint(address.is_shipping_address) and not values.is_default:
		replacement = next((item for item in before_addresses if item.name != address.name), None)
		if replacement:
			replacement.db_set("is_shipping_address", 1)
		else:
			values.is_default = 1

	_apply_values(address, values, locations, price_list_id)
	if not is_valid_uuid(address.custom_supabase_id):
		address.custom_supabase_id = str(uuid4())
	address.save()

	after = _snapshot(_get_linked_addresses(app_user), app_user)
	_sync_remote(supabase, before, after, app_user)
	return {"address": _serialize_address(address), "addresses": _serialized_addresses(app_user)}


@frappe.whitelist()
def delete_user_address(app_user: str, address_name: str) -> dict:
	_get_app_user(app_user, "write")
	address = _get_owned_address(app_user, address_name, "delete")
	before_addresses = _get_linked_addresses(app_user)
	before = _snapshot(before_addresses, app_user)
	was_default = bool(cint(address.is_shipping_address))

	frappe.delete_doc(ADDRESS_DOCTYPE, address.name)
	remaining = _get_linked_addresses(app_user)
	if was_default and remaining:
		remaining[0].db_set("is_shipping_address", 1)

	after = _snapshot(_get_linked_addresses(app_user), app_user)
	_sync_remote(init_supabase(), before, after, app_user)
	return {"deleted": address_name, "addresses": _serialized_addresses(app_user)}
