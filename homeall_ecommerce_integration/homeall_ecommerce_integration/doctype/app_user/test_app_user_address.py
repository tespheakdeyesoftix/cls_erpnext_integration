# Copyright (c) 2026, Tes Pheakdey and contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from homeall_ecommerce_integration.controller import is_valid_uuid
from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_user.app_user_address import (
	_validate_remote_price_list,
	delete_user_address,
	get_user_addresses,
	save_user_address,
)


EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = ["Customer", "App User Type", "Price List"]


class FakeQuery:
	def __init__(self, supabase, table_name, operation, payload=None):
		self.supabase = supabase
		self.table_name = table_name
		self.operation = operation
		self.payload = payload
		self.filters = []

	def eq(self, fieldname, value):
		self.filters.append((fieldname, value))
		return self

	def limit(self, value):
		return self

	def execute(self):
		if self.operation in self.supabase.fail_operations:
			raise RuntimeError(f"Failed {self.operation}")

		if self.table_name == "administrative_locations":
			code = next((value for fieldname, value in self.filters if fieldname == "code"), None)
			rows = [{"code": code}] if code in self.supabase.location_codes else []
			return SimpleNamespace(data=rows)

		if self.table_name == "price_lists":
			price_list_id = next((value for fieldname, value in self.filters if fieldname == "id"), None)
			rows = [{"id": price_list_id}] if price_list_id in self.supabase.price_list_ids else []
			return SimpleNamespace(data=rows)

		if self.operation == "insert":
			rows = [dict(row) for row in self.payload]
			for row in rows:
				self.supabase.addresses[row["id"]] = row
		elif self.operation == "upsert":
			rows = [dict(row) for row in self.payload]
			for row in rows:
				self.supabase.addresses[row["id"]] = row
		elif self.operation == "delete":
			rows = []
			for address_id, row in list(self.supabase.addresses.items()):
				if all(row.get(fieldname) == value for fieldname, value in self.filters):
					rows.append(self.supabase.addresses.pop(address_id))
		else:
			rows = []

		self.supabase.operations.append((self.operation, self.table_name, self.payload, self.filters))
		return SimpleNamespace(data=rows)


class FakeTable:
	def __init__(self, supabase, table_name):
		self.supabase = supabase
		self.table_name = table_name

	def select(self, fields):
		return FakeQuery(self.supabase, self.table_name, "select", fields)

	def insert(self, rows):
		return FakeQuery(self.supabase, self.table_name, "insert", rows)

	def upsert(self, rows, on_conflict=None):
		return FakeQuery(self.supabase, self.table_name, "upsert", rows)

	def delete(self):
		return FakeQuery(self.supabase, self.table_name, "delete")


class FakeSupabase:
	def __init__(self):
		self.addresses = {}
		self.location_codes = set()
		self.price_list_ids = set()
		self.fail_operations = set()
		self.operations = []

	def table(self, table_name):
		return FakeTable(self, table_name)


class UnitTestAppUserAddressPriceList(UnitTestCase):
	def test_synced_price_list_is_accepted(self):
		supabase = FakeSupabase()
		price_list_id = str(uuid4())
		supabase.price_list_ids.add(price_list_id)

		_validate_remote_price_list(supabase, price_list_id, "Selling")

	def test_missing_price_list_has_an_actionable_error(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Synchronize the Price List first"):
			_validate_remote_price_list(FakeSupabase(), str(uuid4()), "Selling")

	def test_price_list_read_failure_does_not_expose_remote_details(self):
		supabase = FakeSupabase()
		supabase.fail_operations.add("select")
		with patch("frappe.log_error"):
			with self.assertRaisesRegex(frappe.ValidationError, "Could not validate the Price List"):
				_validate_remote_price_list(supabase, str(uuid4()), "Selling")

	def test_missing_price_list_blocks_address_save_before_local_or_remote_writes(self):
		from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_user import (
			app_user_address as module,
		)

		address = MagicMock()
		price_list_id = str(uuid4())
		values = frappe._dict(price_list="Selling")
		with (
			patch.object(module, "_get_app_user"),
			patch.object(module, "_parse_values", return_value=values),
			patch.object(module, "_validate_text"),
			patch.object(module, "_get_location_values", return_value={}),
			patch.object(module, "_get_price_list_id", return_value=price_list_id),
			patch.object(module, "_get_owned_address", return_value=address),
			patch.object(module, "_get_linked_addresses", return_value=[]),
			patch.object(module, "init_supabase", return_value=FakeSupabase()),
			patch.object(module, "_apply_values") as apply_values,
			patch.object(module, "_sync_remote") as sync_remote,
		):
			with self.assertRaisesRegex(frappe.ValidationError, "Synchronize the Price List first"):
				save_user_address(str(uuid4()), values, "Home-Shipping")

		address.save.assert_not_called()
		address.db_set.assert_not_called()
		apply_values.assert_not_called()
		sync_remote.assert_not_called()


class IntegrationTestAppUserAddress(IntegrationTestCase):
	INIT_SUPABASE = (
		"homeall_ecommerce_integration.homeall_ecommerce_integration.doctype."
		"app_user.app_user_address.init_supabase"
	)

	def setUp(self):
		super().setUp()
		self.app_user = self.make_app_user()
		self.supabase = FakeSupabase()
		self.supabase.price_list_ids.add(
			frappe.db.get_value("Price List", "Standard Selling", "custom_supabase_id")
		)

	def make_app_user(self):
		user_id = str(uuid4())
		doc = frappe.get_doc(
			{
				"doctype": "App User",
				"name": user_id,
				"username": f"address-{uuid4().hex[:12]}",
				"phone_number": f"+85599{uuid4().int % 900000 + 100000}",
				"full_name": "Address Test User",
				"status": "Active",
			}
		)
		doc.db_insert()
		return doc

	def values(self, **updates):
		values = {
			"label": "Home",
			"recipient_name": "Test Recipient",
			"phone": "+85512345678",
			"address_line1": "Street 123",
			"address_line2": "Building A",
			"city": "Phnom Penh",
			"postal_code": "12000",
			"country": "Cambodia",
			"latitude": 11.5564,
			"longitude": 104.9282,
			"google_place_id": "place-123",
			"formatted_address": "Street 123, Phnom Penh",
			"street": "Street 123",
			"landmark": "Near the market",
			"delivery_note": "Call on arrival",
			"price_list": "Standard Selling",
			"is_default": 0,
		}
		values.update(updates)
		return values

	def save(self, values=None, address_name=None):
		with patch(self.INIT_SUPABASE, return_value=self.supabase):
			return save_user_address(
				self.app_user.name,
				values or self.values(),
				address_name,
			)

	def test_create_generates_shared_uuid_and_links_app_user(self):
		result = self.save()
		address = frappe.get_doc("Address", result["address"]["name"])

		self.assertTrue(is_valid_uuid(address.custom_supabase_id))
		self.assertTrue(address.has_link("App User", self.app_user.name))
		self.assertEqual(address.address_type, "Shipping")
		self.assertEqual(address.is_shipping_address, 1)
		self.assertEqual(address.custom_recipient_name, "Test Recipient")
		self.assertEqual(
			address.custom_price_list_id,
			frappe.db.get_value("Price List", "Standard Selling", "custom_supabase_id"),
		)

		remote = self.supabase.addresses[address.custom_supabase_id]
		self.assertEqual(remote["id"], address.custom_supabase_id)
		self.assertEqual(remote["user_id"], self.app_user.name)
		self.assertEqual(remote["country_code"], "KH")
		self.assertEqual(remote["label"], "Home")
		self.assertTrue(remote["is_default"])
		self.assertIsNotNone(remote["created_at"])

		listed = get_user_addresses(self.app_user.name)["addresses"]
		self.assertEqual(len(listed), 1)
		self.assertEqual(listed[0]["name"], address.name)

	def test_edit_preserves_uuid_and_updates_remote_row(self):
		created = self.save()["address"]
		address_id = created["supabase_id"]
		updated = self.save(
			self.values(label="Warehouse", address_line1="Updated address"),
			created["name"],
		)["address"]

		self.assertEqual(updated["supabase_id"], address_id)
		self.assertEqual(updated["label"], "Warehouse")
		self.assertEqual(self.supabase.addresses[address_id]["label"], "Warehouse")
		self.assertEqual(self.supabase.addresses[address_id]["address_line1"], "Updated address")

	def test_default_switch_and_default_deletion_promote_remaining_address(self):
		first = self.save(self.values(label="Home"))["address"]
		second = self.save(self.values(label="Office", is_default=1))["address"]

		self.assertFalse(self.supabase.addresses[first["supabase_id"]]["is_default"])
		self.assertTrue(self.supabase.addresses[second["supabase_id"]]["is_default"])

		with patch(self.INIT_SUPABASE, return_value=self.supabase):
			result = delete_user_address(self.app_user.name, second["name"])

		self.assertEqual(result["deleted"], second["name"])
		self.assertFalse(frappe.db.exists("Address", second["name"]))
		self.assertNotIn(second["supabase_id"], self.supabase.addresses)
		first_doc = frappe.get_doc("Address", first["name"])
		self.assertEqual(first_doc.is_shipping_address, 1)
		self.assertTrue(self.supabase.addresses[first["supabase_id"]]["is_default"])

	def test_missing_required_field_fails_before_supabase(self):
		with patch(self.INIT_SUPABASE, return_value=self.supabase) as init_supabase:
			with self.assertRaises(frappe.MandatoryError):
				save_user_address(self.app_user.name, self.values(phone=None))
			with self.assertRaises(frappe.MandatoryError):
				save_user_address(self.app_user.name, self.values(price_list=None))
			with self.assertRaises(frappe.ValidationError):
				save_user_address(self.app_user.name, self.values(price_list="Standard Buying"))

		init_supabase.assert_not_called()

	def test_invalid_coordinates_fail_before_supabase(self):
		with patch(self.INIT_SUPABASE, return_value=self.supabase) as init_supabase:
			with self.assertRaises(frappe.ValidationError):
				save_user_address(self.app_user.name, self.values(latitude="not-a-number"))
			with self.assertRaises(frappe.ValidationError):
				save_user_address(self.app_user.name, self.values(longitude=181))

		init_supabase.assert_not_called()

	def test_cannot_edit_another_users_address(self):
		created = self.save()["address"]
		other_user = self.make_app_user()

		with patch(self.INIT_SUPABASE, return_value=self.supabase):
			with self.assertRaises(frappe.PermissionError):
				save_user_address(other_user.name, self.values(), created["name"])

	def test_remote_failure_prevents_committed_local_address(self):
		self.supabase.fail_operations.add("insert")
		with patch(self.INIT_SUPABASE, return_value=self.supabase):
			with self.assertRaises(frappe.ValidationError):
				save_user_address(self.app_user.name, self.values())

		frappe.db.rollback()
		self.assertFalse(
			frappe.db.exists(
				"Dynamic Link",
				{"link_doctype": "App User", "link_name": self.app_user.name},
			)
		)
