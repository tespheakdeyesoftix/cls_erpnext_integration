# Copyright (c) 2026, Tes Pheakdey and Contributors
# See license.txt

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import NAMESPACE_URL, uuid5

import frappe
from frappe.tests import UnitTestCase

from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1 import (
	app_promotion_service as service,
)


ITEM_ID = "55555555-5555-4555-8555-555555555555"
FREE_ITEM_ID = "66666666-6666-4666-8666-666666666666"


def _promotion_rule(**overrides):
	rule = {
		"id": "77777777-7777-4777-8777-777777777777",
		"apply_for": [{
			"apply_for_type": "Item", "apply_for": ITEM_ID, "uom": "Unit", "limit_qty": 100,
			"max_qty_per_order": 10, "max_qty_per_user": 20,
		}],
		"price_discount_slabs": [{
			"min_qty": 1, "max_qty": None, "min_amount": 0, "max_amount": None,
			"rate_or_discount": "Discount Percentage", "discount_percentage": 10,
			"discount_amount": 0, "rate": 0,
		}],
		"product_discount_slabs": [{
			"min_qty": 12, "max_qty": None, "min_amount": 0, "max_amount": None,
			"free_product_id": FREE_ITEM_ID, "free_product_unit": "Ton តោន",
			"free_product_quantity": 1, "free_is_recursive": False,
			"recurse_for": 0, "apply_recursion_over": 0,
		}],
	}
	rule.update(overrides)
	return rule


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

	def test_price_slab_validates_the_selected_json_discount_value(self):
		for discount_type, fieldname in (
			("Rate", "rate"),
			("Discount Amount", "discount_amount"),
			("Discount Percentage", "discount_percentage"),
		):
			with self.subTest(discount_type=discount_type):
				row = dict(rate_or_discount=discount_type, rate=5, discount_amount=5, discount_percentage=5)
				errors = []
				service._validate_price_slab_value(row, "Price Discount Slabs", 1, errors)
				self.assertEqual(errors, [])
				row[fieldname] = 0
				service._validate_price_slab_value(row, "Price Discount Slabs", 1, errors)
				self.assertEqual(len(errors), 1)

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
				rate=2,
			),
			frappe._dict(
				idx=2,
				min_qty=5,
				max_qty=20,
				min_amount=0,
				max_amount=0,
				rate_or_discount="Rate",
				rate=2,
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
			promotion_rules=json.dumps([_promotion_rule()]),
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
		):
			payload = service._prepare_record(doc)

		self.assertEqual(payload["description"], "")
		self.assertEqual(payload["terms_and_conditions"], "")
		self.assertEqual(payload["applicable_for"][0]["applicable_for"], price_list_id)
		self.assertEqual(payload["flash_banner_products"], [item_id, free_item_id])
		self.assertEqual(payload["promotion_rules"], [_promotion_rule()])
		for fieldname in ("apply_for", "price_discount_slabs", "product_discount_slabs"):
			self.assertNotIn(fieldname, payload)
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


class TestAppPromotionJSONRules(UnitTestCase):
	def setUp(self):
		class RuleOnlyPromotion(frappe._dict):
			def __getattr__(self, fieldname):
				if fieldname in ("apply_for", "price_discount_slabs", "product_discount_slabs"):
					raise AssertionError(f"Removed parent field was read: {fieldname}")
				return super().__getattr__(fieldname)

		self.doc = RuleOnlyPromotion(
			name="11111111-1111-4111-8111-111111111111",
			docstatus=1,
			check_permission=MagicMock(),
			title="JSON Promotion",
			business_id="22222222-2222-4222-8222-222222222222",
			start_date="2026-10-21 09:00:00",
			end_date="2026-10-31 12:00:00",
			photo="https://erp.example/files/promotion.jpg",
			promotion_type="Standard",
			promotion_rules=json.dumps([_promotion_rule()]),
			application_scope="product_line",
			applicable_for=[],
			flash_banner_style="style_1",
			upcoming_display="label",
			flash_product_source="apply_for",
			flash_product_limit=6,
			flash_banner_corner_radius=9,
			flash_banner_height=260,
			flash_banner_products=[],
			countdown_placement="top_right",
			card_action_type="native_detail",
		)
		self.names_by_uuid = {("Item", ITEM_ID): "ITEM-1", ("Item", FREE_ITEM_ID): "FREE-1"}
		self.items = {
			name: frappe._dict(
				custom_business_profile=self.doc.business_id,
				custom_supabase_id=item_id,
				item_group="Other Group",
				stock_uom="Unit",
			)
			for (doctype, item_id), name in self.names_by_uuid.items()
		}
		self.lookup = self.enterContext(patch.object(
			service.frappe.db, "get_value",
			side_effect=lambda dt, filters, field: self.names_by_uuid.get((dt, filters["custom_supabase_id"])),
		))
		self.enterContext(patch.object(service, "_get_item_data", side_effect=self.items.get))

	def test_submit_upserts_parsed_rules_without_removed_columns(self):
		supabase = MagicMock()
		supabase.table.return_value.upsert.return_value.execute.return_value = SimpleNamespace(data=[])
		with (
			patch.object(service.frappe, "only_for"),
			patch.object(service.frappe, "get_doc", return_value=self.doc),
			patch.object(service.sync, "init_supabase", return_value=supabase),
			patch.object(service.frappe.db, "set_value") as set_value,
			patch.object(service.frappe.db, "commit"),
		):
			result = service.submit_to_app_database(self.doc.name)

		payload = supabase.table.return_value.upsert.call_args.args[0]
		supabase.table.assert_called_once_with("promotions")
		self.assertEqual(payload["promotion_rules"], [_promotion_rule()])
		self.assertIsInstance(payload["promotion_rules"], list)
		for fieldname in ("apply_for", "price_discount_slabs", "product_discount_slabs"):
			self.assertNotIn(fieldname, payload)
		self.doc.check_permission.assert_called_once_with("write")
		set_value.assert_called_once_with("App Promotion", self.doc.name, "is_synced", 1, update_modified=False)
		self.assertTrue(result["success"])

	def test_multiple_rule_ids_units_nulls_and_recursion_are_preserved(self):
		rules = [_promotion_rule(), _promotion_rule(id="another-rule")]
		rules[1]["apply_for"][0]["uom"] = "Case"
		rules[1]["product_discount_slabs"][0].update(
			free_product_unit="Bag", free_is_recursive=True, recurse_for=10, apply_recursion_over=20,
		)
		for value in (json.dumps(rules), deepcopy(rules)):
			with self.subTest(encoded=isinstance(value, str)):
				self.doc.promotion_rules = value
				payload = service._prepare_record(self.doc)
				self.assertEqual(payload["promotion_rules"], rules)
				self.assertEqual(self.doc.promotion_rules, value)

	def test_blank_rules_do_not_require_removed_child_fields(self):
		for value in (None, "", "  ", [], "[]"):
			with self.subTest(value=value):
				self.doc.promotion_rules = value
				self.assertEqual(service._prepare_record(self.doc)["promotion_rules"], [])

	def test_invalid_rule_shapes_are_rejected_before_supabase_is_called(self):
		for value in (
			"{", "{}", "null", "false", "[null]", '[{"apply_for": {}}]',
			[{"price_discount_slabs": None}], [{"product_discount_slabs": ["invalid"]}],
		):
			with self.subTest(value=value):
				self.doc.promotion_rules = value
				with (
					patch.object(service.sync, "init_supabase") as init_supabase,
					self.assertRaisesRegex(frappe.ValidationError, "Promotion Rule"),
				):
					service._upsert_promotion(self.doc)
				init_supabase.assert_not_called()

	def test_raw_json_numeric_fields_must_be_finite_numbers(self):
		for value in ("not-a-number", {}, [], True, float("nan"), float("inf")):
			with self.subTest(value=value):
				rule = _promotion_rule()
				rule["price_discount_slabs"][0]["max_qty"] = value
				self.doc.promotion_rules = json.dumps([rule])
				with self.assertRaisesRegex(frappe.ValidationError, "max_qty must be a finite number"):
					service.validate_promotion(self.doc)

	def test_same_slab_ranges_are_allowed_in_separate_rules(self):
		self.doc.promotion_rules = [_promotion_rule(), _promotion_rule(id="second")]
		self.assertEqual(service.validate_promotion(self.doc), "quantity")

	def test_overlapping_ranges_in_a_rule_report_rule_and_row_numbers(self):
		rule = _promotion_rule()
		rule["price_discount_slabs"].append(deepcopy(rule["price_discount_slabs"][0]))
		self.doc.promotion_rules = [_promotion_rule(), rule]
		with self.assertRaisesRegex(frappe.ValidationError, "Promotion Rule 2 Price Discount Slabs rows 1 and 2"):
			service.validate_promotion(self.doc)

	def test_mixed_qualification_bases_are_checked_within_each_rule(self):
		rule = _promotion_rule()
		rule["price_discount_slabs"][0].update(min_qty=0, min_amount=100)
		self.doc.promotion_rules = [rule]
		with self.assertRaisesRegex(frappe.ValidationError, "Promotion Rule 1: all discount slabs"):
			service.validate_promotion(self.doc)

	def test_quantity_rule_requires_cart_uom_even_after_an_amount_rule(self):
		amount_rule = _promotion_rule(product_discount_slabs=[])
		amount_rule["price_discount_slabs"][0].update(min_qty=0, min_amount=100)
		self.doc.promotion_rules = [amount_rule, _promotion_rule(id="quantity-rule")]
		self.doc.application_scope = "eligible_cart"
		with self.assertRaisesRegex(frappe.ValidationError, "Cart Qualification UOM is required"):
			service.validate_promotion(self.doc)
		self.doc.cart_qualification_uom = "Unit"
		self.assertEqual(service.validate_promotion(self.doc), "quantity")

	def test_zero_gift_quantity_uses_new_json_field_name(self):
		rule = _promotion_rule()
		rule["product_discount_slabs"][0]["free_product_quantity"] = 0
		self.doc.promotion_rules = [rule]
		with self.assertRaisesRegex(frappe.ValidationError, "Product Discount Slabs row 1.*greater than zero"):
			service.validate_promotion(self.doc)

	def test_invalid_and_missing_uuid_references_have_rule_context(self):
		for fieldname, identifier in (("apply_for", "apply_for"), ("product_discount_slabs", "free_product_id")):
			for value in (None, "invalid", "88888888-8888-4888-8888-888888888888"):
				with self.subTest(fieldname=fieldname, value=value):
					rule = _promotion_rule()
					rule[fieldname][0][identifier] = value
					self.doc.promotion_rules = [rule]
					with self.assertRaisesRegex(frappe.ValidationError, "Promotion Rule 1.*row 1"):
						service.validate_promotion(self.doc)

	def test_unsupported_target_type_does_not_query_an_arbitrary_doctype(self):
		rule = _promotion_rule(product_discount_slabs=[])
		rule["apply_for"][0]["apply_for_type"] = "Customer"
		self.doc.promotion_rules = [rule]
		with self.assertRaisesRegex(frappe.ValidationError, "Apply For row 1 has an unsupported type"):
			service.validate_promotion(self.doc)
		self.lookup.assert_not_called()

	def test_uuid_lookups_are_reused_across_rules(self):
		self.doc.promotion_rules = [_promotion_rule(), _promotion_rule(id="second")]
		service.validate_promotion(self.doc)
		self.assertEqual(self.lookup.call_count, 2)

	def test_uom_is_required_for_item_targets(self):
		for value in (None, "", "  ", False, []):
			with self.subTest(value=value):
				rule = _promotion_rule()
				rule["apply_for"][0]["uom"] = value
				self.doc.promotion_rules = [rule]
				with self.assertRaisesRegex(frappe.ValidationError, "Apply For row 1: UOM is required"):
					service.validate_promotion(self.doc)

	def test_item_groups_do_not_require_uom(self):
		group_id = "88888888-8888-4888-8888-888888888888"
		self.names_by_uuid[("Item Group", group_id)] = "Group A"
		rule = _promotion_rule(apply_for=[{"apply_for_type": "Item Group", "apply_for": group_id}])
		errors = []
		references = service._validate_rule_dependencies([rule], errors)
		self.assertEqual(errors, [])
		self.assertEqual(references[("Item Group", group_id)], "Group A")

	def test_business_validation_still_covers_json_targets_and_gifts(self):
		for name in ("ITEM-1", "FREE-1"):
			with self.subTest(name=name):
				self.items[name].custom_business_profile = "other-business"
				with self.assertRaisesRegex(frappe.ValidationError, f"Item {name} does not belong"):
					service.validate_promotion(self.doc)
				self.items[name].custom_business_profile = self.doc.business_id

	def test_manual_banner_can_match_targets_in_a_later_rule(self):
		self.doc.promotion_type = "Flash Sale"
		self.doc.flash_product_source = "manual"
		self.doc.flash_banner_products = [frappe._dict(product="FREE-1")]
		with patch.object(service, "_resolve_supabase_uuid", return_value=FREE_ITEM_ID):
			with self.assertRaisesRegex(frappe.ValidationError, "not eligible through Promotion Rules"):
				service.validate_promotion(self.doc)
			self.doc.promotion_rules = [_promotion_rule(), _promotion_rule(
				id="second", product_discount_slabs=[],
				apply_for=[{"apply_for_type": "Item", "apply_for": FREE_ITEM_ID, "uom": "Unit"}],
			)]
			self.assertEqual(service.validate_promotion(self.doc), "quantity")


class TestAppPromotionGroupEligibility(UnitTestCase):
	def setUp(self):
		self.business_id = "22222222-2222-4222-8222-222222222222"
		self.items = []
		self.groups = {
			"Group A": {"Group A", "Child A", "Grandchild A"},
			"Group B": {"Group B"},
		}

	def _uuid(self, doctype, name):
		return str(uuid5(NAMESPACE_URL, f"promotion-test/{doctype}/{name}"))

	def _add_item(self, name, *, group="Group A", business="selected", published=1):
		item = frappe._dict(
			name=name,
			item_group=group,
			custom_business_profile=self.business_id if business == "selected" else business,
			custom_is_publish=published,
			custom_supabase_id=self._uuid("Item", name),
		)
		self.items.append(item)
		return item

	def _query_items(self, doctype, *, filters, fields, limit_page_length):
		self.assertEqual(doctype, "Item")
		self.assertEqual(limit_page_length, 1)
		matches = self.items
		for field, value in filters.items():
			if isinstance(value, list):
				self.assertEqual(value[0], "in")
				matches = [item for item in matches if item.get(field) in value[1]]
			else:
				matches = [item for item in matches if item.get(field) == value]
		return [frappe._dict({field: item.get(field) for field in fields}) for item in matches[:limit_page_length]]

	def _validate(self, **overrides):
		doc = frappe._dict(
			business_id=self.business_id,
			promotion_rules=[{
				"apply_for": [{
					"apply_for_type": "Item Group", "apply_for": self._uuid("Item Group", "Group A"),
				}],
			}],
		)
		doc.update(overrides)
		errors = []
		item_data = {item.name: item for item in self.items}
		names_by_uuid = {
			("Item", item.custom_supabase_id): item.name for item in self.items
		} | {("Item Group", self._uuid("Item Group", name)): name for name in self.groups}
		with (
			patch.object(service, "_descendant_item_groups", side_effect=self.groups.__getitem__),
			patch.object(service.frappe, "get_all", side_effect=self._query_items),
			patch.object(service, "_get_item_data", side_effect=item_data.get),
			patch.object(service.frappe.db, "get_value", side_effect=lambda dt, filters, field:
				names_by_uuid.get((dt, filters["custom_supabase_id"]))),
		):
			rules = service._parse_promotion_rules(doc.promotion_rules)
			references = service._validate_rule_dependencies(rules, errors)
			service._validate_product_business_and_eligibility(doc, rules, references, errors)
		return errors

	def test_mixed_business_group_with_five_published_matches_passes(self):
		for position in range(5):
			self._add_item(f"MATCH-{position}")
		for position, business in enumerate((None, "", "other-business", None, "other-business")):
			self._add_item(f"UNRELATED-{position}", business=business)

		self.assertEqual(self._validate(), [])

	def test_published_match_only_in_grandchild_group_passes(self):
		self._add_item("UNRELATED", business="other-business")
		self._add_item("NESTED-MATCH", group="Grandchild A")

		self.assertEqual(self._validate(), [])

	def test_groups_without_published_business_matches_fail(self):
		for scenario in ("empty", "unpublished", "other-business", "unassigned", "outside-subtree"):
			with self.subTest(scenario=scenario):
				self.items = []
				if scenario == "unpublished":
					self._add_item("UNPUBLISHED", published=0)
				elif scenario == "other-business":
					self._add_item("OTHER-BUSINESS", business="other-business")
				elif scenario == "unassigned":
					self._add_item("UNASSIGNED", business=None)
				elif scenario == "outside-subtree":
					self._add_item("OUTSIDE", group="Group B")

				self.assertEqual(
					self._validate(),
					[
						"Item Group Group A and its child groups contain no published products "
						f"assigned to Business Profile {self.business_id}."
					],
				)

	def test_each_selected_group_requires_a_match(self):
		self._add_item("MATCH-A")
		apply_for = [
			frappe._dict(apply_for_type="Item Group", apply_for=self._uuid("Item Group", group))
			for group in ("Group A", "Group B")
		]
		errors = self._validate(promotion_rules=[{"apply_for": apply_for}])
		self.assertEqual(len(errors), 1)
		self.assertIn("Item Group Group B and its child groups", errors[0])

		self._add_item("MATCH-B", group="Group B")
		self.assertEqual(self._validate(promotion_rules=[{"apply_for": apply_for}]), [])

	def test_explicit_products_from_another_business_still_fail(self):
		self._add_item("GROUP-MATCH")
		self._add_item("OTHER", business="other-business")
		for overrides in (
			{"promotion_rules": [{"apply_for": [{
				"apply_for_type": "Item", "apply_for": self._uuid("Item", "OTHER"), "uom": "Unit",
			}]}]},
			{"promotion_rules": [{"product_discount_slabs": [{
				"free_product_id": self._uuid("Item", "OTHER"),
			}]}]},
			{"flash_banner_products": [frappe._dict(product="OTHER")]},
			{"card_action_type": "product_detail", "card_action_product_id": "OTHER"},
		):
			with self.subTest(overrides=overrides):
				self.assertEqual(
					self._validate(**overrides),
					[f"Item OTHER does not belong to Business Profile {self.business_id}."],
				)

	def test_manual_banner_product_in_grandchild_group_remains_eligible(self):
		self._add_item("BANNER", group="Grandchild A")
		self.assertEqual(
			self._validate(
				promotion_type="Flash Sale",
				flash_product_source="manual",
				flash_banner_products=[frappe._dict(product="BANNER")],
			),
			[],
		)
