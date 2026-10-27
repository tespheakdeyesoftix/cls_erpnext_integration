# Copyright (c) 2026, Tes Pheakdey and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import UnitTestCase

from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1 import (
	app_promotion_service as service,
)


class TestAppPromotion(UnitTestCase):
	def test_standard_timestamps_cover_full_cambodia_day(self):
		self.assertEqual(
			service._promotion_timestamp("2026-10-21 09:15:00", "Standard", is_end=False),
			"2026-10-21T00:00:00+07:00",
		)
		self.assertEqual(
			service._promotion_timestamp("2026-10-31 09:15:00", "Standard", is_end=True),
			"2026-10-31T23:59:59+07:00",
		)

	def test_flash_sale_timestamp_preserves_entered_local_time(self):
		self.assertEqual(
			service._promotion_timestamp("2026-10-21 09:15:00", "Flash Sale", is_end=False),
			"2026-10-21T09:15:00+07:00",
		)

	def test_standard_promotion_allows_same_calendar_day(self):
		errors = []
		service._validate_dates(
			frappe._dict(
				promotion_type="Standard",
				start_date="2026-10-21 20:00:00",
				end_date="2026-10-21 08:00:00",
			),
			errors,
		)

		self.assertEqual(errors, [])

	def test_price_slab_maps_only_selected_discount_value(self):
		payload = service._price_slab_payload(
			frappe._dict(
				min_qty=1,
				max_qty=0,
				min_amount=0,
				max_amount=0,
				rate_or_discount="Discount Percentage",
				price_or_discount_value=15,
			)
		)

		self.assertEqual(payload["max_qty"], None)
		self.assertEqual(payload["discount_percentage"], 15)
		self.assertEqual(payload["discount_amount"], 0)
		self.assertEqual(payload["rate"], 0)

	def test_slab_validation_detects_mixed_basis_and_overlaps(self):
		errors = []
		rows = [
			frappe._dict(
				idx=1,
				min_qty=1,
				max_qty=10,
				min_amount=5,
				max_amount=0,
				rate_or_discount="Rate",
				price_or_discount_value=2,
			),
			frappe._dict(
				idx=2,
				min_qty=5,
				max_qty=20,
				min_amount=0,
				max_amount=0,
				rate_or_discount="Rate",
				price_or_discount_value=2,
			),
		]

		service._validate_slab_rows(
			rows,
			"Price Discount Slabs",
			errors,
			service._validate_price_slab_value,
		)

		self.assertTrue(any("either Min Qty or Min Amount" in error for error in errors))

	def test_prepare_record_maps_uuid_fields_and_ordered_products(self):
		business_id = "22222222-2222-4222-8222-222222222222"
		price_list_id = "33333333-3333-4333-8333-333333333333"
		user_type_id = "44444444-4444-4444-8444-444444444444"
		item_id = "55555555-5555-4555-8555-555555555555"
		free_item_id = "66666666-6666-4666-8666-666666666666"
		doc = frappe._dict(
			name="11111111-1111-4111-8111-111111111111",
			title="October Promotion",
			description=None,
			photo="/files/promotion.jpg",
			start_date="2026-10-21 09:00:00",
			end_date="2026-10-31 12:00:00",
			terms_and_conditions=None,
			business_id=business_id,
			promotion_type="Standard",
			priority=100,
			badge_bg_color="#E53935",
			applicable_for=[
				frappe._dict(applicable_for_type="Price List", applicable_for="Retail"),
				frappe._dict(applicable_for_type="App User Type", applicable_for=user_type_id),
			],
			apply_for=[
				frappe._dict(
					apply_for_type="Item",
					apply_for="ITEM-1",
					limit_qty=100,
					max_qty_per_order=10,
					max_qty_per_user=20,
				)
			],
			price_discount_slabs=[
				frappe._dict(
					min_qty=1,
					max_qty=0,
					min_amount=0,
					max_amount=0,
					rate_or_discount="Discount Percentage",
					price_or_discount_value=10,
				)
			],
			product_discount_slabs=[
				frappe._dict(
					min_qty=12,
					max_qty=0,
					min_amount=0,
					max_amount=0,
					free_product="FREE-1",
					free_product_qty=1,
					is_recursive=0,
					recurse_for=0,
					apply_recursion_over=0,
				)
			],
			show_countdown=1,
			show_sold_progress=0,
			flash_banner_style="style_1",
			show_upcoming=0,
			upcoming_display="label",
			flash_product_source="manual",
			flash_product_limit=6,
			flash_banner_products=[
				frappe._dict(product="ITEM-1"),
				frappe._dict(product="FREE-1"),
			],
			flash_banner_full_width=1,
			flash_banner_corner_radius=16,
			countdown_placement="bottom_center",
			flash_banner_height=160,
			card_action_type="native_detail",
			card_action_product_id=None,
			card_action_url=None,
			application_scope="product_line",
			cart_qualification_uom=None,
			maximum_cart_discount_amount=50,
		)
		uuid_map = {
			("Price List", "Retail"): price_list_id,
			("App User Type", user_type_id): user_type_id,
			("Item", "ITEM-1"): item_id,
			("Item", "FREE-1"): free_item_id,
		}

		with (
			patch.object(service, "validate_promotion"),
			patch.object(service, "_public_photo_url", return_value="https://erp.example/files/promotion.jpg"),
			patch.object(service, "_resolve_supabase_uuid", side_effect=lambda dt, name: uuid_map[(dt, name)]),
			patch.object(service, "_get_item_data", return_value=frappe._dict(stock_uom="Unit")),
		):
			payload = service._prepare_record(doc)

		self.assertEqual(payload["description"], "")
		self.assertEqual(payload["terms_and_conditions"], "")
		self.assertEqual(payload["applicable_for"][0]["applicable_for"], price_list_id)
		self.assertEqual(payload["flash_banner_products"], [item_id, free_item_id])
		self.assertEqual(payload["product_discount_slabs"][0]["free_product_unit"], "Unit")
		self.assertEqual(payload["start_date"], "2026-10-21T00:00:00+07:00")
		self.assertEqual(payload["end_date"], "2026-10-31T23:59:59+07:00")

	def test_pricing_rpc_uses_exact_name_and_argument(self):
		supabase = MagicMock()
		supabase.rpc.return_value.execute.return_value = SimpleNamespace(data={"created": 2})

		with patch.object(service.sync, "init_supabase", return_value=supabase):
			result = service._execute_promotion_rpc(
				"11111111-1111-4111-8111-111111111111",
				"api_generate_promotion_pricing_rules",
			)

		supabase.rpc.assert_called_once_with(
			"api_generate_promotion_pricing_rules",
			{"p_promotion_id": "11111111-1111-4111-8111-111111111111"},
		)
		self.assertTrue(result["success"])

	def test_notification_endpoint_uses_exact_rpc(self):
		doc = frappe._dict(
			name="11111111-1111-4111-8111-111111111111",
			docstatus=1,
			is_synced=1,
		)
		supabase = MagicMock()
		supabase.rpc.return_value.execute.return_value = SimpleNamespace(data={"notified": 5})

		with (
			patch.object(service.frappe, "only_for"),
			patch.object(service, "_get_submitted_promotion", return_value=doc),
			patch.object(service.sync, "init_supabase", return_value=supabase),
		):
			result = service.notify_promotion_users(doc.name)

		supabase.rpc.assert_called_once_with(
			"api_notify_dsku_promotion",
			{"p_promotion_id": doc.name},
		)
		self.assertTrue(result["success"])

	def test_rpc_action_rejects_unsynced_promotion(self):
		doc = frappe._dict(
			name="11111111-1111-4111-8111-111111111111",
			docstatus=1,
			is_synced=0,
			check_permission=MagicMock(),
		)

		with (
			patch.object(service.frappe, "get_doc", return_value=doc),
			self.assertRaises(frappe.ValidationError),
		):
			service._get_submitted_promotion(doc.name, require_synced=True)

	def test_removal_calls_disable_rpc_for_cancelled_unsynced_promotion(self):
		doc = frappe._dict(
			name="11111111-1111-4111-8111-111111111111",
			docstatus=2,
			is_synced=0,
			check_permission=MagicMock(),
		)
		supabase = MagicMock()
		supabase.rpc.return_value.execute.return_value = SimpleNamespace(data=None)

		with (
			patch.object(service.frappe, "only_for") as only_for,
			patch.object(service.frappe, "get_doc", return_value=doc),
			patch.object(service.sync, "init_supabase", return_value=supabase),
		):
			result = service.remove_promotion_from_app(doc.name)

		only_for.assert_called_once_with("System Manager")
		doc.check_permission.assert_called_once_with("write")
		supabase.rpc.assert_called_once_with("disable_promotion", {"promotion_id": doc.name})
		self.assertTrue(result["success"])

	def test_removal_rejects_non_cancelled_promotions_and_invalid_uuid(self):
		for status, name in (
			(0, "11111111-1111-4111-8111-111111111111"),
			(1, "11111111-1111-4111-8111-111111111111"),
			(2, "invalid-uuid"),
		):
			with self.subTest(docstatus=status, name=name):
				doc = frappe._dict(name=name, docstatus=status, check_permission=MagicMock())
				with (
					patch.object(service.frappe, "only_for"),
					patch.object(service.frappe, "get_doc", return_value=doc),
					patch.object(service.sync, "init_supabase") as init_supabase,
					self.assertRaises(frappe.ValidationError),
				):
					service.remove_promotion_from_app(name)
				init_supabase.assert_not_called()

	def test_removal_checks_system_manager_before_loading_document(self):
		with (
			patch.object(service.frappe, "only_for", side_effect=frappe.PermissionError),
			patch.object(service.frappe, "get_doc") as get_doc,
			self.assertRaises(frappe.PermissionError),
		):
			service.remove_promotion_from_app("11111111-1111-4111-8111-111111111111")

		get_doc.assert_not_called()

	def test_removal_rejects_document_permission_failure(self):
		doc = frappe._dict(
			name="11111111-1111-4111-8111-111111111111",
			docstatus=2,
			check_permission=MagicMock(side_effect=frappe.PermissionError),
		)
		with (
			patch.object(service.frappe, "only_for"),
			patch.object(service.frappe, "get_doc", return_value=doc),
			patch.object(service.sync, "init_supabase") as init_supabase,
			self.assertRaises(frappe.PermissionError),
		):
			service.remove_promotion_from_app(doc.name)

		init_supabase.assert_not_called()

	def test_removal_propagates_rpc_failure(self):
		doc = frappe._dict(
			name="11111111-1111-4111-8111-111111111111",
			docstatus=2,
			check_permission=MagicMock(),
		)
		supabase = MagicMock()
		supabase.rpc.return_value.execute.side_effect = RuntimeError("offline")
		with (
			patch.object(service.frappe, "only_for"),
			patch.object(service.frappe, "get_doc", return_value=doc),
			patch.object(service.sync, "init_supabase", return_value=supabase),
			patch.object(service, "_log_supabase_error") as log_error,
			self.assertRaisesRegex(RuntimeError, "offline"),
		):
			service.remove_promotion_from_app(doc.name)

		log_error.assert_called_once_with("Promotion RPC: disable_promotion", doc.name)

	def test_submit_endpoint_checks_system_manager_before_loading_document(self):
		with (
			patch.object(service.frappe, "only_for", side_effect=frappe.PermissionError),
			patch.object(service, "_get_submitted_promotion") as get_promotion,
			self.assertRaises(frappe.PermissionError),
		):
			service.submit_to_app_database("11111111-1111-4111-8111-111111111111")

		get_promotion.assert_not_called()

	def test_private_photo_is_rejected(self):
		private_file = frappe._dict(name="private.jpg", is_private=1)

		with (
			patch.object(service.frappe.db, "get_value", return_value=private_file),
			self.assertRaises(frappe.ValidationError),
		):
			service._public_photo_url("/private/files/private.jpg")

	def test_successful_upsert_marks_promotion_synced(self):
		doc = frappe._dict(name="11111111-1111-4111-8111-111111111111")
		supabase = MagicMock()
		supabase.table.return_value.upsert.return_value.execute.return_value = SimpleNamespace(data=[{"id": doc.name}])

		with (
			patch.object(service, "_prepare_record", return_value={"id": doc.name}),
			patch.object(service.sync, "init_supabase", return_value=supabase),
			patch.object(service.frappe.db, "set_value") as set_value,
			patch.object(service.frappe.db, "commit") as commit,
		):
			result = service._upsert_promotion(doc)

		set_value.assert_called_once_with(
			"App Promotion",
			doc.name,
			"is_synced",
			1,
			update_modified=False,
		)
		commit.assert_called_once()
		self.assertTrue(result["success"])

	def test_failed_upsert_does_not_mark_promotion_synced(self):
		doc = frappe._dict(name="11111111-1111-4111-8111-111111111111")
		supabase = MagicMock()
		supabase.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("offline")

		with (
			patch.object(service, "_prepare_record", return_value={"id": doc.name}),
			patch.object(service.sync, "init_supabase", return_value=supabase),
			patch.object(service, "_log_supabase_error"),
			patch.object(service.frappe.db, "set_value") as set_value,
			patch.object(service.frappe.db, "rollback") as rollback,
			self.assertRaises(RuntimeError),
		):
			service._upsert_promotion(doc)

		set_value.assert_not_called()
		rollback.assert_called_once()
