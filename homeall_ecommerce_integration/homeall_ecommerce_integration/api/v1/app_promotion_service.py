import json
import math
import re
from datetime import datetime, time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import flt, get_datetime, get_url

from homeall_ecommerce_integration.controller import is_valid_uuid
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1 import (
	fn_sync_to_supabase as sync,
)


CAMBODIA_TIMEZONE = ZoneInfo("Asia/Phnom_Penh")
PRICE_DISCOUNT_TYPES = {"Rate", "Discount Percentage", "Discount Amount"}
RULE_NUMERIC_FIELDS = {
	"apply_for": ("limit_qty", "max_qty_per_order", "max_qty_per_user"),
	"price_discount_slabs": (
		"min_qty", "max_qty", "min_amount", "max_amount", "rate", "discount_amount", "discount_percentage",
	),
	"product_discount_slabs": (
		"min_qty", "max_qty", "min_amount", "max_amount", "free_product_quantity",
		"recurse_for", "apply_recursion_over",
	),
}
CARD_ACTION_TYPES = {"native_detail", "product_detail", "promotion_products", "webview"}
COUNTDOWN_PLACEMENTS = {
	"top_left",
	"top_center",
	"top_right",
	"middle_left",
	"middle_center",
	"middle_right",
	"bottom_left",
	"bottom_center",
	"bottom_right",
}


def sync_record(name: str | None = None, batch_size: int = 100):
	"""Synchronize one promotion or all submitted, unsynchronized promotions."""
	if name:
		doc = frappe.get_doc("App Promotion", name)
		_assert_submitted(doc)
		return _upsert_promotion(doc)

	return sync.sync_to_supabase(
		doctype="App Promotion",
		table_name="promotions",
		prepare_data=_prepare_record,
		batch_size=batch_size,
		sync_field="is_synced",
		filters={"docstatus": 1, "is_synced": 0},
	)


@frappe.whitelist(methods=["POST"])
def submit_to_app_database(name: str):
	frappe.only_for("System Manager")
	doc = _get_submitted_promotion(name)
	return _upsert_promotion(doc)


@frappe.whitelist(methods=["POST"])
def remove_promotion_from_app(name: str):
	frappe.only_for("System Manager")
	if not name:
		frappe.throw("App Promotion is required.")

	doc = frappe.get_doc("App Promotion", name)
	doc.check_permission("write")
	if doc.docstatus != 2:
		frappe.throw("Only cancelled App Promotions can be removed from the App Database.")
	if not is_valid_uuid(doc.name):
		frappe.throw("The App Promotion name must be a valid UUID.")

	return _execute_promotion_rpc(doc.name, "disable_promotion", id_parameter="promotion_id")


@frappe.whitelist(methods=["POST"])
def generate_promotion_pricing_rules(name: str):
	frappe.only_for("System Manager")
	doc = _get_submitted_promotion(name, require_synced=True)
	return _execute_promotion_rpc(doc.name, "api_generate_promotion_pricing_rules")


@frappe.whitelist(methods=["POST"])
def notify_promotion_users(name: str):
	frappe.only_for("System Manager")
	doc = _get_submitted_promotion(name, require_synced=True)
	return _execute_promotion_rpc(doc.name, "api_notify_dsku_promotion")


def _get_submitted_promotion(name: str, require_synced: bool = False):
	if not name:
		frappe.throw("App Promotion is required.")

	doc = frappe.get_doc("App Promotion", name)
	doc.check_permission("write")
	_assert_submitted(doc)

	if require_synced and not doc.is_synced:
		frappe.throw("Submit this promotion to the App Database before running this action.")

	return doc


def _assert_submitted(doc):
	if doc.docstatus == 2:
		frappe.throw("Only submitted App Promotions can be published to Supabase.")


def _upsert_promotion(doc):
	data = _prepare_record(doc)

	try:
		response = (
			sync.init_supabase()
			.table("promotions")
			.upsert(data, on_conflict="id")
			.execute()
		)
		frappe.db.set_value(
			"App Promotion",
			doc.name,
			"is_synced",
			1,
			update_modified=False,
		)
		frappe.db.commit()
		return {"success": True, "promotion_id": doc.name, "data": response.data}
	except Exception:
		frappe.db.rollback()
		_log_supabase_error("Promotion Upsert", doc.name)
		raise


def _execute_promotion_rpc(
	promotion_id: str, rpc_name: str, *, id_parameter: str = "p_promotion_id"
):
	try:
		response = (
			sync.init_supabase()
			.rpc(rpc_name, {id_parameter: promotion_id})
			.execute()
		)
		return {"success": True, "promotion_id": promotion_id, "data": response.data}
	except Exception:
		_log_supabase_error(f"Promotion RPC: {rpc_name}", promotion_id)
		raise


def _log_supabase_error(operation: str, promotion_id: str):
	frappe.log_error(
		title=f"Supabase {operation} Error",
		message=f"Promotion: {promotion_id}\n\n{frappe.get_traceback()}",
	)


def validate_promotion(doc):
	errors: list[str] = []
	rules = _parse_promotion_rules(doc.get("promotion_rules"))

	if not is_valid_uuid(doc.name):
		errors.append("The App Promotion name must be a valid UUID.")

	if not is_valid_uuid(doc.business_id):
		errors.append("Business Profile must have a valid Supabase UUID.")

	_validate_dates(doc, errors)
	_validate_display_settings(doc, errors)
	_validate_card_action(doc, errors)
	qualification_basis = _validate_discount_slabs(rules, errors)

	if (
		qualification_basis == "quantity"
		and doc.application_scope in {"eligible_cart", "entire_cart"}
		and not doc.cart_qualification_uom
	):
		errors.append(
			"Cart Qualification UOM is required for quantity-based eligible-cart or entire-cart promotions."
		)

	if flt(doc.maximum_cart_discount_amount) < 0:
		errors.append("Maximum Cart Discount Amount cannot be negative.")

	_validate_dependency_uuids(doc, errors)
	references = _validate_rule_dependencies(rules, errors)
	_validate_product_business_and_eligibility(doc, rules, references, errors)

	if errors:
		frappe.throw("Promotion validation failed:\n- " + "\n- ".join(_unique(errors)))

	_public_photo_url(doc.photo)
	return qualification_basis


def _validate_dates(doc, errors: list[str]):
	if not doc.start_date:
		errors.append("Start Date is required.")
		return

	if not doc.end_date:
		return

	start = _as_cambodia_datetime(doc.start_date)
	end = _as_cambodia_datetime(doc.end_date)
	if doc.promotion_type == "Standard":
		if end.date() < start.date():
			errors.append("End Date cannot be before Start Date.")
	elif end <= start:
		errors.append("End Date must be later than Start Date.")


def _validate_display_settings(doc, errors: list[str]):
	if doc.promotion_type not in {"Standard", "Flash Sale"}:
		errors.append("Promotion Type must be Standard or Flash Sale.")

	if doc.application_scope not in {"product_line", "eligible_cart", "entire_cart"}:
		errors.append("Application Scope is invalid.")

	if doc.flash_banner_style not in {"style_1", "style_2", "style_3"}:
		errors.append("Flash Banner Style is invalid.")

	if doc.upcoming_display not in {"label", "countdown"}:
		errors.append("Upcoming Display is invalid.")

	if doc.flash_product_source not in {"apply_for", "manual"}:
		errors.append("Flash Product Source is invalid.")

	if not 1 <= int(doc.flash_product_limit or 0) <= 12:
		errors.append("Flash Product Limit must be between 1 and 12.")

	if not 0 <= int(doc.flash_banner_corner_radius or 0) <= 40:
		errors.append("Flash Banner Corner Radius must be between 0 and 40.")

	if not 120 <= int(doc.flash_banner_height or 0) <= 400:
		errors.append("Flash Banner Height must be between 120 and 400.")

	if doc.countdown_placement not in COUNTDOWN_PLACEMENTS:
		errors.append("Countdown Placement is invalid.")

	if doc.badge_bg_color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", doc.badge_bg_color):
		errors.append("Badge BG Color must use #RRGGBB format.")

	banner_products = list(doc.flash_banner_products or [])
	if len(banner_products) > 12:
		errors.append("Flash Banner Products cannot contain more than 12 products.")

	if doc.promotion_type == "Flash Sale" and doc.flash_product_source == "manual" and not banner_products:
		errors.append("At least one Flash Banner Product is required when the product source is manual.")


def _validate_card_action(doc, errors: list[str]):
	action_type = doc.card_action_type
	product = doc.card_action_product_id
	url = (doc.card_action_url or "").strip()

	if action_type not in CARD_ACTION_TYPES:
		errors.append("Card Action Type is invalid.")
		return

	if action_type in {"native_detail", "promotion_products"}:
		if product or url:
			errors.append(f"{action_type} cannot have a Card Action Product or URL.")
	elif action_type == "product_detail":
		if not product:
			errors.append("Card Action Product is required for product_detail.")
		if url:
			errors.append("Card Action URL must be empty for product_detail.")
	elif action_type == "webview":
		if product:
			errors.append("Card Action Product must be empty for webview.")
		parsed = urlparse(url)
		if parsed.scheme != "https" or not parsed.netloc:
			errors.append("Card Action URL must be a valid HTTPS URL for webview.")


def _parse_promotion_rules(value):
	if value is None or (isinstance(value, str) and not value.strip()):
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			frappe.throw("Promotion Rules must contain a valid JSON array.")
	if not isinstance(value, list):
		frappe.throw("Promotion Rules must be a JSON array.")

	for index, rule in enumerate(value, start=1):
		if not isinstance(rule, dict):
			frappe.throw(f"Promotion Rule {index} must be a JSON object.")
		for fieldname, numeric_fields in RULE_NUMERIC_FIELDS.items():
			rows = rule.get(fieldname, [])
			if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
				frappe.throw(f"Promotion Rule {index}: {fieldname} must be an array of row objects.")
			for position, row in enumerate(rows, start=1):
				for numeric_field in numeric_fields:
					number = row.get(numeric_field)
					if number is not None and (
						isinstance(number, bool) or not isinstance(number, int | float) or not math.isfinite(number)
					):
						frappe.throw(
							f"Promotion Rule {index} {fieldname} row {position}: {numeric_field} must be a finite number."
						)
	return value


def _validate_discount_slabs(rules, errors: list[str]):
	all_bases: set[str] = set()
	for index, rule in enumerate(rules, start=1):
		price_basis = _validate_slab_rows(
			rule.get("price_discount_slabs", []),
			f"Promotion Rule {index} Price Discount Slabs",
			errors,
			_validate_price_slab_value,
		)
		product_basis = _validate_slab_rows(
			rule.get("product_discount_slabs", []),
			f"Promotion Rule {index} Product Discount Slabs",
			errors,
			_validate_product_slab_value,
		)
		bases = price_basis | product_basis
		if len(bases) > 1:
			errors.append(
				f"Promotion Rule {index}: all discount slabs must use the same quantity or amount qualification basis."
			)
		all_bases.update(bases)

	# Independent rules can use different bases; any quantity rule needs a cart UOM.
	if "quantity" in all_bases:
		return "quantity"
	return "amount" if "amount" in all_bases else None


def _validate_slab_rows(rows, label: str, errors: list[str], value_validator):
	bases: set[str] = set()
	ranges: dict[str, list[tuple[float, float, int]]] = {"quantity": [], "amount": []}

	for position, row in enumerate(rows, start=1):
		row_number = row.get("idx") or position
		min_qty = flt(row.get("min_qty"))
		max_qty = flt(row.get("max_qty"))
		min_amount = flt(row.get("min_amount"))
		max_amount = flt(row.get("max_amount"))
		quantity_based = min_qty > 0
		amount_based = min_amount > 0

		if quantity_based == amount_based:
			errors.append(
				f"{label} row {row_number} must have either Min Qty or Min Amount greater than zero."
			)
			value_validator(row, label, row_number, errors)
			continue

		if quantity_based:
			basis = "quantity"
			minimum, maximum = min_qty, max_qty
			if min_amount != 0 or max_amount != 0:
				errors.append(f"{label} row {row_number} cannot mix quantity and amount fields.")
		else:
			basis = "amount"
			minimum, maximum = min_amount, max_amount
			if min_qty != 0 or max_qty != 0:
				errors.append(f"{label} row {row_number} cannot mix quantity and amount fields.")

		bases.add(basis)
		if maximum < 0 or (maximum and maximum < minimum):
			errors.append(f"{label} row {row_number} has an invalid maximum value.")
		else:
			ranges[basis].append((minimum, maximum or math.inf, row_number))

		value_validator(row, label, row_number, errors)

	for basis, entries in ranges.items():
		entries.sort(key=lambda entry: entry[0])
		for previous, current in zip(entries, entries[1:], strict=False):
			if current[0] <= previous[1]:
				errors.append(
					f"{label} rows {previous[2]} and {current[2]} have overlapping {basis} ranges."
				)

	return bases


def _validate_price_slab_value(row, label: str, row_number: int, errors: list[str]):
	discount_type = row.get("rate_or_discount")
	if not isinstance(discount_type, str) or discount_type not in PRICE_DISCOUNT_TYPES:
		errors.append(f"{label} row {row_number} has an invalid Discount Type.")
		return
	value_field = {
		"Rate": "rate",
		"Discount Percentage": "discount_percentage",
		"Discount Amount": "discount_amount",
	}[discount_type]
	if flt(row.get(value_field)) <= 0:
		errors.append(f"{label} row {row_number} must have a Price or Discount Value greater than zero.")


def _validate_product_slab_value(row, label: str, row_number: int, errors: list[str]):
	if flt(row.get("free_product_quantity")) <= 0:
		errors.append(f"{label} row {row_number} must have a Free Product Qty greater than zero.")


def _validate_dependency_uuids(doc, errors: list[str]):
	for row in doc.applicable_for or []:
		if row.applicable_for_type not in {"Price List", "App User Type"}:
			errors.append(f"Applicable For row {row.idx} has an unsupported type.")
			continue
		_check_dependency_uuid(row.applicable_for_type, row.applicable_for, errors)

	for row in doc.flash_banner_products or []:
		_check_dependency_uuid("Item", row.product, errors)

	if doc.card_action_type == "product_detail":
		_check_dependency_uuid("Item", doc.card_action_product_id, errors)


def _validate_rule_dependencies(rules, errors: list[str]):
	"""Resolve the UUIDs already stored in JSON to local records for validation only."""
	references: dict[tuple[str, str], str | None] = {}

	def resolve(doctype, value, label):
		if not isinstance(value, str) or not is_valid_uuid(value):
			errors.append(f"{label} requires a valid {doctype} Supabase UUID.")
			return
		key = (doctype, value)
		if key not in references:
			references[key] = frappe.db.get_value(doctype, {"custom_supabase_id": value}, "name")
		if not references[key]:
			errors.append(f"{label}: no local {doctype} matches Supabase UUID {value}.")

	for index, rule in enumerate(rules, start=1):
		for position, row in enumerate(rule.get("apply_for", []), start=1):
			label = f"Promotion Rule {index} Apply For row {position}"
			doctype = row.get("apply_for_type")
			if doctype not in ("Item", "Item Group"):
				errors.append(f"{label} has an unsupported type.")
				continue
			if doctype == "Item" and (not isinstance(row.get("uom"), str) or not row["uom"].strip()):
				errors.append(f"{label}: UOM is required when Apply For Type is Item.")
			resolve(doctype, row.get("apply_for"), label)
		for position, row in enumerate(rule.get("product_discount_slabs", []), start=1):
			resolve(
				"Item", row.get("free_product_id"),
				f"Promotion Rule {index} Product Discount Slabs row {position}",
			)
	return references


def _check_dependency_uuid(doctype: str, name: str | None, errors: list[str]):
	if not name:
		errors.append(f"{doctype} is required in a promotion mapping row.")
		return

	value = _resolve_supabase_uuid(doctype, name)
	if not is_valid_uuid(value):
		errors.append(f"{doctype} {name} does not have a valid Supabase UUID.")


def _resolve_supabase_uuid(doctype: str, name: str | None):
	if not name:
		return None
	if doctype in {"Business Profile", "App User Type"}:
		return name
	if doctype in {"Price List", "Item", "Item Group"}:
		return frappe.db.get_value(doctype, name, "custom_supabase_id")
	return None


def _validate_product_business_and_eligibility(doc, rules, references, errors: list[str]):
	direct_items: set[str] = set()
	selected_groups: set[str] = set()
	eligible_groups: set[str] = set()
	all_product_names = {
		name for (doctype, _uuid), name in references.items() if doctype == "Item" and name
	}

	for rule in rules:
		for row in rule.get("apply_for", []):
			doctype, value = row.get("apply_for_type"), row.get("apply_for")
			if doctype not in ("Item", "Item Group") or not isinstance(value, str):
				continue
			name = references.get((doctype, value))
			if name:
				(direct_items if doctype == "Item" else selected_groups).add(name)

	for group in sorted(selected_groups):
		group_names = _descendant_item_groups(group)
		eligible_groups.update(group_names)
		matching_items = frappe.get_all(
			"Item",
			filters={
				"item_group": ["in", list(group_names)],
				"custom_business_profile": doc.business_id,
				"custom_is_publish": 1,
			},
			fields=["name"],
			limit_page_length=1,
		)
		if not matching_items:
			errors.append(
				f"Item Group {group} and its child groups contain no published products "
				f"assigned to Business Profile {doc.business_id}."
			)

	for row in doc.flash_banner_products or []:
		if row.product:
			all_product_names.add(row.product)
	if doc.card_action_type == "product_detail" and doc.card_action_product_id:
		all_product_names.add(doc.card_action_product_id)

	item_data = {name: _get_item_data(name) for name in all_product_names}
	for name, item in item_data.items():
		if not item:
			errors.append(f"Item {name} does not exist.")
		elif item.custom_business_profile != doc.business_id:
			errors.append(f"Item {name} does not belong to Business Profile {doc.business_id}.")

	if doc.promotion_type == "Flash Sale" and doc.flash_product_source == "manual":
		for row in doc.flash_banner_products or []:
			item = item_data.get(row.product)
			if item and row.product not in direct_items and item.item_group not in eligible_groups:
				errors.append(f"Flash Banner Product {row.product} is not eligible through Promotion Rules Apply For.")


def _descendant_item_groups(group_name: str):
	group = frappe.db.get_value("Item Group", group_name, ["lft", "rgt"], as_dict=True)
	if not group:
		return {group_name}
	return set(
		frappe.get_all(
			"Item Group",
			filters={"lft": [">=", group.lft], "rgt": ["<=", group.rgt]},
			pluck="name",
		)
	) or {group_name}


def _get_item_data(item_name: str):
	return frappe.db.get_value(
		"Item",
		item_name,
		["custom_business_profile", "item_group", "stock_uom", "custom_supabase_id"],
		as_dict=True,
	)


def _prepare_record(record):
	validate_promotion(record)

	return {
		"id": record.name,
		"name": record.title,
		"name_km": record.title_km or record.title,
		"name_zh": record.title_zh or record.title,
		"description": record.description or "",
		"photo_url": _public_photo_url(record.photo),
		"start_date": _promotion_timestamp(record.start_date, record.promotion_type, is_end=False),
		"end_date": (
			_promotion_timestamp(record.end_date, record.promotion_type, is_end=True)
			if record.end_date
			else None
		),
		"terms_and_conditions": record.terms_and_conditions or "",
		"business_id": record.business_id,
		"promotion_type": record.promotion_type,
		"priority": int(record.priority or 0),
		"badge_bg_color": record.badge_bg_color or None,
		"applicable_for": [
			{
				"applicable_for_type": row.applicable_for_type,
				"applicable_for": _resolve_supabase_uuid(row.applicable_for_type, row.applicable_for),
			}
			for row in record.applicable_for or []
		],
		"promotion_rules": _parse_promotion_rules(record.get("promotion_rules")),
		"show_countdown": bool(record.show_countdown),
		"show_sold_progress": bool(record.show_sold_progress),
		"flash_banner_style": record.flash_banner_style,
		"show_upcoming": bool(record.show_upcoming),
		"upcoming_display": record.upcoming_display,
		"flash_product_source": record.flash_product_source,
		"flash_product_limit": int(record.flash_product_limit),
		"flash_banner_products": [
			_resolve_supabase_uuid("Item", row.product) for row in record.flash_banner_products or []
		],
		"flash_banner_full_width": bool(record.flash_banner_full_width),
		"flash_banner_corner_radius": int(record.flash_banner_corner_radius),
		"countdown_placement": record.countdown_placement,
		"flash_banner_height": int(record.flash_banner_height),
		"card_action_type": record.card_action_type,
		"card_action_product_id": (
			_resolve_supabase_uuid("Item", record.card_action_product_id)
			if record.card_action_type == "product_detail"
			else None
		),
		"card_action_url": record.card_action_url.strip() if record.card_action_type == "webview" else None,
		"application_scope": record.application_scope,
		"cart_qualification_uom": record.cart_qualification_uom or None,
		"maximum_cart_discount_amount": (
			flt(record.maximum_cart_discount_amount) if record.maximum_cart_discount_amount else None
		),
		"disabled": record.disabled or False,
	}


def _promotion_timestamp(value, promotion_type: str, is_end: bool):
	local_value = _as_cambodia_datetime(value)
	if promotion_type == "Standard":
		boundary = time(23, 59, 59) if is_end else time.min
		local_value = datetime.combine(local_value.date(), boundary, tzinfo=CAMBODIA_TIMEZONE)
	return local_value.isoformat()


def _as_cambodia_datetime(value):
	value = get_datetime(value)
	if value.tzinfo is None:
		return value.replace(tzinfo=CAMBODIA_TIMEZONE)
	return value.astimezone(CAMBODIA_TIMEZONE)


def _public_photo_url(photo: str | None):
	photo = (photo or "").strip()
	if not photo:
		frappe.throw("Promotion Photo is required.")

	parsed = urlparse(photo)
	if parsed.scheme:
		if parsed.scheme != "https" or not parsed.netloc:
			frappe.throw("Promotion Photo must be a valid public HTTPS URL.")
		return photo

	file_record = frappe.db.get_value("File", {"file_url": photo}, ["name", "is_private"], as_dict=True)
	if not file_record:
		frappe.throw("The attached Promotion Photo file could not be found.")
	if file_record.is_private or photo.startswith("/private/files/"):
		frappe.throw("Promotion Photo must be publicly accessible; private files are not supported.")

	return get_url(photo)


def _unique(values: list[str]):
	return list(dict.fromkeys(values))
