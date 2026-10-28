from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import frappe
from frappe import _
from frappe.utils import cint, cstr, getdate

from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync import init_supabase

MAX_PAGE_SIZE = 100
ORDER_SEARCH_BATCH_SIZE = 500
ORDER_FIELDS = (
	"id,status,currency,total_quantity,subtotal,tax_amount,total_amount,erp_order_number,"
	"erp_sync_status,request_items,created_at,updated_at,delivery_address_snapshot,"
	"payment_method,payment_status,note,erp_customer,pricing_user_type_name,"
	"discount_amount,product_discount_amount,cart_discount_amount,"
	"payment_transaction_id,payment_reference,payment_expires_at,payment_qr_image_url,"
	"items:order_items(*),applied_cart_promotions:order_promotions(*)"
)
ORDER_STATUS_HISTORY_FIELDS = "id,order_id,from_status,to_status,reason,changed_by,changed_at"
ORDER_STATUSES = frozenset(
	{
		"pending",
		"accepted",
		"rejected",
		"processing",
		"out_for_delivery",
		"delivered",
		"completed",
		"cancelled",
	}
)
PRODUCT_FIELDS = "id,erp_item_code,name,description,uom,price,currency,default_image_url"


def _require_staff():
	from homeall_ecommerce_integration.notifications.api import require_staff

	require_staff()


@frappe.whitelist(methods=["GET"])
def get_order(order_id: str) -> dict[str, Any]:
	"""Fetch an exact order regardless of the list's filters or current page."""
	_require_staff()
	order_id = _validate_order_id(order_id)
	client = init_supabase()
	rows = client.table("orders").select(ORDER_FIELDS).eq("id", order_id).limit(1).execute().data or []
	if not rows:
		frappe.throw(_("Order not found."), frappe.DoesNotExistError)
	_enrich_order_items(rows)
	order = rows[0]
	order["status_history"] = _get_status_history(order_id, client)
	return order


def _parse_date(value: str | None, label: str) -> date | None:
	if not value:
		return None

	try:
		return getdate(value)
	except Exception:
		frappe.throw(_("កាលបរិច្ឆេទ{0}មិនត្រឹមត្រូវ").format(label))


def _validate_order_id(value: str | None) -> str:
	try:
		return str(UUID(cstr(value)))
	except (TypeError, ValueError, AttributeError):
		frappe.throw(_("លេខសម្គាល់ការបញ្ជាទិញមិនត្រឹមត្រូវ"))


def _normalize_order_search(value: str | None) -> str:
	search = cstr(value).strip().removeprefix("#").strip().lower()
	if search and not re.fullmatch(r"[0-9a-f-]{1,36}", search):
		frappe.throw(_("សូមបញ្ចូល UUID ឬផ្នែកនៃ UUID សម្រាប់ស្វែងរកការបញ្ជាទិញ"))
	return search


def _get_order(order_id: str, client: Any) -> dict[str, Any]:
	response = (
		client
		.table("orders")
		.select("id,status")
		.eq("id", order_id)
		.limit(1)
		.execute()
	)
	orders = response.data or []
	if not orders:
		frappe.throw(_("រកមិនឃើញការបញ្ជាទិញនេះទេ"), exc=frappe.DoesNotExistError)

	return orders[0]


def _get_status_history(order_id: str, client: Any) -> list[dict[str, Any]]:
	response = (
		client
		.table("order_status_history")
		.select(ORDER_STATUS_HISTORY_FIELDS)
		.eq("order_id", order_id)
		.order("changed_at", desc=True)
		.execute()
	)
	return response.data or []


def _get_order_items(order: dict[str, Any]) -> list[dict[str, Any]]:
	# Checkout requests omit awarded gifts and the final, persisted pricing.
	items = order.get("items") or []
	return items if isinstance(items, list) else []


def _enrich_order_items(orders: list[dict[str, Any]]) -> None:
	product_ids = {
		str(item.get("product_id"))
		for order in orders
		for item in _get_order_items(order)
		if item.get("product_id")
	}
	if not product_ids:
		return

	products_response = (
		init_supabase()
		.table("products")
		.select(PRODUCT_FIELDS)
		.in_("id", sorted(product_ids))
		.execute()
	)
	products = {str(row.get("id")): row for row in (products_response.data or [])}

	for order in orders:
		enriched_items = []
		for item in _get_order_items(order):
			product = products.get(str(item.get("product_id")), {})
			enriched_items.append({**item, "product": product})
		order["items"] = enriched_items


def _apply_order_filters(query: Any, start: date | None, end: date | None, status: str | None):
	if start:
		query = query.gte("created_at", start.isoformat())
	if end:
		query = query.lt("created_at", (end + timedelta(days=1)).isoformat())
	if status:
		query = query.eq("status", status)
	return query


def _search_order_ids(client, search, start, end, status, offset, page_size):
	# PostgREST cannot apply LIKE to UUIDs or cast them in filters. Read only IDs,
	# match their text here, then load details for the requested matching page.
	matching_ids = []
	total = 0
	scanned = 0
	candidate_count = None
	while True:
		query = client.table("orders").select("id", count="exact" if scanned == 0 else None)
		query = _apply_order_filters(query, start, end, status)
		response = (
			query.order("created_at", desc=True).order("id", desc=True)
			.range(scanned, scanned + ORDER_SEARCH_BATCH_SIZE - 1).execute()
		)
		if response.count is not None:
			candidate_count = response.count
		rows = response.data or []
		if not rows:
			break
		for row in rows:
			order_id = str(row["id"])
			if search in order_id.lower():
				if offset <= total < offset + page_size:
					matching_ids.append(order_id)
				total += 1
		scanned += len(rows)
		if candidate_count is not None and scanned >= candidate_count:
			break
	return matching_ids, total


@frappe.whitelist(methods=["GET"])
def get_orders(
	page: int | str = 1,
	page_size: int | str = 20,
	start_date: str | None = None,
	end_date: str | None = None,
	status: str | None = None,
	search_id: str | None = None,
) -> dict[str, Any]:
	"""Return one filtered, newest-first page of Supabase orders."""
	_require_staff()
	page = max(cint(page), 1)
	page_size = min(max(cint(page_size), 1), MAX_PAGE_SIZE)
	start = _parse_date(start_date, _("ចាប់ផ្តើម"))
	end = _parse_date(end_date, _("បញ្ចប់"))
	selected_status = cstr(status).strip().lower() or None
	search = _normalize_order_search(search_id)

	if selected_status and selected_status not in ORDER_STATUSES:
		frappe.throw(_("ស្ថានភាពការបញ្ជាទិញមិនត្រឹមត្រូវ"))

	if start and end and start > end:
		frappe.throw(_("ថ្ងៃចាប់ផ្តើមមិនអាចនៅក្រោយថ្ងៃបញ្ចប់បានទេ"))

	offset = (page - 1) * page_size
	client = init_supabase()
	if search:
		matching_ids, total = _search_order_ids(
			client, search, start, end, selected_status, offset, page_size,
		)
		orders = []
		if matching_ids:
			response = client.table("orders").select(ORDER_FIELDS).in_("id", matching_ids).execute()
			by_id = {str(row["id"]): row for row in (response.data or [])}
			orders = [by_id[order_id] for order_id in matching_ids if order_id in by_id]
	else:
		query = client.table("orders").select(ORDER_FIELDS, count="exact")
		query = _apply_order_filters(query, start, end, selected_status)
		response = query.order("created_at", desc=True).range(offset, offset + page_size - 1).execute()
		orders = response.data or []
		total = response.count or 0
	_enrich_order_items(orders)

	return {
		"orders": orders,
		"page": page,
		"page_size": page_size,
		"total": total,
		"total_pages": max((total + page_size - 1) // page_size, 1),
	}


@frappe.whitelist(methods=["GET"])
def get_order_status_history(order_id: str) -> dict[str, Any]:
	_require_staff()
	order_id = _validate_order_id(order_id)
	client = init_supabase()
	order = _get_order(order_id, client)
	return {
		"status": order.get("status"),
		"history": _get_status_history(order_id, client),
	}


@frappe.whitelist(methods=["POST"])
def update_order_status(
	order_id: str,
	status: str,
	reason: str | None = None,
) -> dict[str, Any]:
	_require_staff()
	order_id = _validate_order_id(order_id)
	target_status = cstr(status).strip().lower()
	if target_status not in ORDER_STATUSES:
		frappe.throw(_("ស្ថានភាពការបញ្ជាទិញមិនត្រឹមត្រូវ"))

	clean_reason = cstr(reason).strip() or None
	if clean_reason and len(clean_reason) > 2000:
		frappe.throw(_("មូលហេតុមិនអាចលើសពី ២០០០ តួអក្សរបានទេ"))

	changed_by = cstr(
		frappe.db.get_value("User", frappe.session.user, "full_name")
	).strip() or frappe.session.user

	client = init_supabase()
	order = _get_order(order_id, client)
	previous_status = cstr(order.get("status")).strip().lower() or None

	if target_status == previous_status:
		return {
			"updated": False,
			"status": previous_status,
			"history": _get_status_history(order_id, client),
		}

	history_before = _get_status_history(order_id, client)
	history_ids_before = {row.get("id") for row in history_before}
	update_response = (
		client
		.table("orders")
		.update({"status": target_status})
		.eq("id", order_id)
		.eq("status", previous_status)
		.execute()
	)
	if not (update_response.data or []):
		frappe.throw(_("ស្ថានភាពត្រូវបានផ្លាស់ប្តូររួចហើយ។ សូមផ្ទុកឡើងវិញ ហើយព្យាយាមម្តងទៀត។"))


	history_after = _get_status_history(order_id, client)
	trigger_history = next(
		(
			row
			for row in history_after
			if (
				row.get("id") not in history_ids_before
				and row.get("from_status") == previous_status
				and row.get("to_status") == target_status
			)
		),
		None,
	)

	if trigger_history:
		history_updates = {"changed_by": changed_by}
		if clean_reason:
			history_updates["reason"] = clean_reason

		if any(trigger_history.get(field) != value for field, value in history_updates.items()):
			try:
				(
					client
					.table("order_status_history")
					.update(history_updates)
					.eq("id", trigger_history.get("id"))
					.execute()
				)
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					"Order status history metadata update failed",
				)
	else:
		history_row = {
			"id": str(uuid4()),
			"order_id": order_id,
			"from_status": previous_status,
			"to_status": target_status,
			"reason": clean_reason,
			"changed_by": changed_by,
		}

		try:
			client.table("order_status_history").insert(history_row).execute()
		except Exception:
			try:
				(
					client
					.table("orders")
					.update({"status": previous_status})
					.eq("id", order_id)
					.eq("status", target_status)
					.execute()
				)
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					"Order status history rollback failed",
				)
			raise

	return {
		"updated": True,
		"status": target_status,
		"history": _get_status_history(order_id, client),
	}
