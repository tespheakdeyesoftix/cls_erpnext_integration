from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1 import orders


class TestOrderDetails(TestCase):
	def test_stored_lines_keep_gifts_repeated_products_and_checkout_prices(self):
		stored_lines = [
			{"id": "purchased", "product_id": "product", "uom": "Box", "quantity": 2, "unit_price": 9, "line_total": 16},
			{"id": "gift", "product_id": "product", "uom": "Unit", "line_type": "free", "quantity": 1, "unit_price": 0, "line_total": 0},
		]
		row = {
			"items": deepcopy(stored_lines),
			"request_items": {"items": [{"product_id": "wrong", "quantity": 100}]},
		}
		client = MagicMock()
		client.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
			{"id": "product", "name": "Current name", "price": 999}
		]
		with patch.object(orders, "init_supabase", return_value=client):
			orders._enrich_order_items([row])

		self.assertEqual([{key: line[key] for key in original} for line, original in zip(row["items"], stored_lines, strict=True)], stored_lines)
		self.assertEqual(row["items"][1]["product"]["price"], 999)
		client.table.return_value.select.return_value.in_.assert_called_once_with("id", ["product"])

	def test_empty_stored_items_do_not_reconstruct_checkout_request(self):
		row = {"items": [], "request_items": {"items": [{"product_id": "product"}]}}
		with patch.object(orders, "init_supabase") as init:
			orders._enrich_order_items([row])
			init.assert_not_called()
		self.assertEqual(row["items"], [])

	def test_missing_product_does_not_remove_saved_order_line(self):
		row = {"items": [{"id": "gift", "product_id": "missing", "product_name": "Saved gift", "line_total": 0}]}
		client = MagicMock()
		client.table.return_value.select.return_value.in_.return_value.execute.return_value.data = []
		with patch.object(orders, "init_supabase", return_value=client):
			orders._enrich_order_items([row])
		self.assertEqual(row["items"][0]["product_name"], "Saved gift")
		self.assertEqual(row["items"][0]["product"], {})

	def test_both_list_and_direct_details_load_saved_lines_and_promotions(self):
		order_id = "00000000-0000-4000-8000-000000001010"
		row = {"id": order_id, "items": [], "applied_cart_promotions": [{"promotion_name": "Saved campaign", "discount_amount": 11}]}
		client = MagicMock()
		query = client.table.return_value
		query.select.return_value = query
		query.eq.return_value = query
		query.limit.return_value = query
		query.order.return_value = query
		query.range.return_value = query
		query.execute.return_value = SimpleNamespace(data=[row], count=1)
		with (
			patch.object(orders, "_require_staff"),
			patch.object(orders, "_", side_effect=lambda text: text),
			patch.object(orders, "init_supabase", return_value=client),
			patch.object(orders, "_get_status_history", return_value=[]),
		):
			detail = orders.get_order(order_id)
			listed = orders.get_orders()["orders"][0]
		self.assertEqual(detail["applied_cart_promotions"], listed["applied_cart_promotions"])
		for call in query.select.call_args_list:
			fields = call.args[0]
			self.assertIn("items:order_items(*)", fields)
			self.assertIn("applied_cart_promotions:order_promotions(*)", fields)
			self.assertIn("product_discount_amount", fields)
			self.assertIn("cart_discount_amount", fields)


class TestOrderSearch(TestCase):
	def setUp(self):
		self.client = MagicMock()
		self.query = MagicMock()
		self.id_query = MagicMock()
		for query in (self.query, self.id_query):
			for method in ("gte", "lt", "eq", "in_", "order", "range"):
				getattr(query, method).return_value = query
			query.execute.return_value = SimpleNamespace(data=[], count=0)
		self.client.table.return_value.select.side_effect = (
			lambda fields, **kwargs: self.id_query if fields == "id" else self.query
		)
		for mock in (
			patch.object(orders, "_require_staff"),
			patch.object(orders, "_", side_effect=lambda text: text),
			patch.object(orders, "init_supabase", return_value=self.client),
		):
			mock.start()
			self.addCleanup(mock.stop)

	def test_search_accepts_displayed_id_full_uuid_and_middle_fragment(self):
		order_id = "148398ff-24fd-446c-8372-cf08a5339c2f"
		other_id = "83272585-132b-4878-ab0d-f7a8c9c2030d"
		self.id_query.execute.return_value = SimpleNamespace(
			data=[{"id": other_id}, {"id": order_id}], count=2,
		)
		self.query.execute.return_value = SimpleNamespace(data=[{"id": order_id, "items": []}])
		for entered, expected in (
			("  #148398FF  ", "148398ff"),
			("398FF-24FD", "398ff-24fd"),
			("148398FF-24FD-446C-8372-CF08A5339C2F", "148398ff-24fd-446c-8372-cf08a5339c2f"),
		):
			with self.subTest(entered=entered):
				self.assertEqual(orders._normalize_order_search(entered), expected)
				result = orders.get_orders(search_id=entered)
				self.assertEqual([row["id"] for row in result["orders"]], [order_id])
				self.assertEqual(result["total"], 1)
				self.query.in_.assert_called_with("id", [order_id])
		self.id_query.like.assert_not_called()
		self.query.like.assert_not_called()

	def test_search_combines_with_date_status_and_pagination(self):
		ids = [f"148398ff-24fd-446c-8372-{index:012d}" for index in range(3)]
		self.id_query.execute.return_value = SimpleNamespace(data=[{"id": value} for value in ids], count=3)
		self.query.execute.return_value = SimpleNamespace(data=[{"id": ids[2], "items": []}])
		result = orders.get_orders(
			page=2, page_size=2, search_id="398ff-24fd", status="pending",
			start_date="2026-10-01", end_date="2026-10-28",
		)
		self.id_query.gte.assert_called_once_with("created_at", "2026-10-01")
		self.id_query.lt.assert_called_once_with("created_at", "2026-10-29")
		self.id_query.eq.assert_called_once_with("status", "pending")
		self.query.in_.assert_called_once_with("id", [ids[2]])
		self.assertEqual([row["id"] for row in result["orders"]], [ids[2]])
		self.assertEqual(result["total"], 3)
		self.assertEqual(result["total_pages"], 2)

	def test_blank_search_leaves_order_list_unfiltered(self):
		for entered in (None, "", "  ", "#"):
			orders.get_orders(search_id=entered)
		self.query.like.assert_not_called()
		self.id_query.execute.assert_not_called()

	def test_search_scans_beyond_the_first_database_batch_and_preserves_page_order(self):
		self.id_query.execute.side_effect = [
			SimpleNamespace(data=[{"id": "abc-1"}, {"id": "other-1"}], count=5),
			SimpleNamespace(data=[{"id": "other-2"}, {"id": "abc-2"}], count=None),
			SimpleNamespace(data=[{"id": "abc-3"}], count=None),
		]
		self.query.execute.return_value = SimpleNamespace(
			data=[{"id": "abc-2", "items": []}, {"id": "abc-1", "items": []}],
		)
		with patch.object(orders, "ORDER_SEARCH_BATCH_SIZE", 2):
			result = orders.get_orders(search_id="abc", page_size=2)
		self.assertEqual(self.id_query.range.call_args_list, [((0, 1),), ((2, 3),), ((4, 5),)])
		self.assertEqual([row["id"] for row in result["orders"]], ["abc-1", "abc-2"])
		self.assertEqual(result["total"], 3)
		self.assertEqual(result["total_pages"], 2)

	def test_no_matches_does_not_fetch_order_details(self):
		self.id_query.execute.return_value = SimpleNamespace(data=[{"id": "abc"}], count=1)
		result = orders.get_orders(search_id="def")
		self.assertEqual(result["orders"], [])
		self.assertEqual(result["total"], 0)
		self.assertEqual(result["total_pages"], 1)
		self.query.execute.assert_not_called()

	def test_search_rejects_wildcards_and_non_uuid_text_before_querying(self):
		with patch.object(orders.frappe, "throw", side_effect=ValueError):
			for entered in ("%", "_", "*", "pending", "a" * 37, "abc,def", "abc def"):
				with self.subTest(entered=entered), self.assertRaises(ValueError):
					orders.get_orders(search_id=entered)
		self.client.table.assert_not_called()

	def test_search_still_requires_staff_access(self):
		with patch.object(orders, "_require_staff", side_effect=PermissionError):
			with self.assertRaises(PermissionError):
				orders.get_orders(search_id="148398ff")
		self.client.table.assert_not_called()
