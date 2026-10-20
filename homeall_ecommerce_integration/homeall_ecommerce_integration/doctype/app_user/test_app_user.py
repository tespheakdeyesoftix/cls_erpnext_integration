# Copyright (c) 2026, Tes Pheakdey and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_user.app_user import (
	DISABLED_AUTH_BAN_DURATION,
	_normalize_cambodian_phone,
	_normalize_username,
	reset_app_user_password,
	set_app_user_enabled,
)


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = ["Customer", "App User Type", "Price List"]


class IntegrationTestAppUser(IntegrationTestCase):
	"""
	Integration tests for AppUser.
	Use this class for testing interactions between multiple components.
	"""

	INIT_SUPABASE = (
		"homeall_ecommerce_integration.homeall_ecommerce_integration.doctype."
		"app_user.app_user.init_supabase"
	)

	def setUp(self):
		super().setUp()
		self.auth_user_id = str(uuid4())
		self.username = f"app-user-{uuid4().hex[:8]}"
		self.local_phone = f"099{uuid4().int % 900000 + 100000}"
		self.e164_phone = f"+855{self.local_phone[1:]}"

	def make_supabase(self, user_id: str | None = None):
		user_id = user_id if user_id is not None else self.auth_user_id
		supabase = MagicMock()
		supabase.auth.admin.create_user.return_value = SimpleNamespace(
			user=SimpleNamespace(id=user_id)
		)
		supabase.auth.admin.update_user_by_id.return_value = SimpleNamespace(
			user=SimpleNamespace(id=user_id)
		)
		profiles = MagicMock()
		profiles.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
			SimpleNamespace(data=[{"id": user_id}])
		)
		profiles.update.return_value.eq.return_value.execute.return_value = SimpleNamespace(
			data=[{"id": user_id}]
		)
		profiles.delete.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])
		supabase.table.side_effect = lambda table_name: {
			"profiles": profiles,
		}[table_name]
		supabase.profiles = profiles
		return supabase

	def make_app_user(self, **values):
		data = {
			"doctype": "App User",
			"username": self.username,
			"password": "a-secure-password",
			"phone_number": self.local_phone,
			"full_name": "New User",
			"is_dsku_user": 1,
		}
		data.update(values)
		return frappe.get_doc(data)

	def test_provisions_auth_and_profile_using_auth_id_as_name(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			doc = self.make_app_user(
				username="New.User",
				phone_number=self.local_phone,
				email_address="Contact@Example.COM",
			).insert()

		self.assertEqual(doc.name, self.auth_user_id)
		self.assertEqual(doc.username, "new.user")
		self.assertEqual(doc.phone_number, self.e164_phone)
		supabase.auth.admin.create_user.assert_called_once_with(
			{
				"email": "new.user@dsku.invalid",
				"phone": self.e164_phone,
				"password": "a-secure-password",
				"email_confirm": True,
				"phone_confirm": True,
				"user_metadata": {
					"full_name": "New User",
					"username": "new.user",
					"preferred_username": "new.user",
					"app_key": "dsku-wholesale",
					"homeall_password_enabled": True,
				},
			}
		)
		supabase.profiles.update.assert_called_once_with(
			{
				"username": "new.user",
				"full_name": "New User",
				"phone": self.e164_phone,
				"email": "contact@example.com",
				"erp_customer": None,
				"is_dsku_user": True,
				"default_price_list_id": None,
				"user_type_id": None,
				"status": "Active",
			}
		)
		supabase.profiles.update.return_value.eq.assert_called_once_with(
			"id", self.auth_user_id
		)

		doc.reload()
		self.assertIsNone(doc.password)
		self.assertIsNone(doc.get_password(raise_exception=False))

	def test_normalizes_supported_cambodian_phone_formats(self):
		for phone_number in (
			self.local_phone,
			self.e164_phone.removeprefix("+"),
			self.e164_phone,
		):
			with self.subTest(phone_number=phone_number):
				self.assertEqual(_normalize_cambodian_phone(phone_number), self.e164_phone)

	def test_normalizes_username_to_lowercase(self):
		self.assertEqual(_normalize_username(" New.User-1 "), "new.user-1")

	def test_username_change_updates_only_supabase_profile(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			doc = self.make_app_user().insert()
			supabase.profiles.update.reset_mock()

			doc.username = " Changed.User "
			doc.save()

		self.assertEqual(doc.username, "changed.user")
		doc.reload()
		self.assertEqual(doc.username, "changed.user")
		supabase.profiles.update.assert_called_once_with({"username": "changed.user"})
		supabase.profiles.update.return_value.eq.assert_called_once_with(
			"id", self.auth_user_id
		)
		supabase.auth.admin.create_user.assert_called_once()
		supabase.auth.admin.update_user_by_id.assert_not_called()

	def test_username_change_registers_profile_rollback_compensation(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			doc = self.make_app_user().insert()
			supabase.profiles.update.reset_mock()

			callbacks_before = len(frappe.db.after_rollback._functions)
			doc.username = "rollback.user"
			doc.save()

		new_callbacks = list(frappe.db.after_rollback._functions)[callbacks_before:]
		rollback_callbacks = [
			callback
			for callback in new_callbacks
			if getattr(callback, "__qualname__", "").endswith(
				"AppUser.before_save.<locals>.<lambda>"
			)
		]
		self.assertEqual(len(rollback_callbacks), 1)
		rollback_compensation = rollback_callbacks[0]
		frappe.db.after_rollback._functions.remove(rollback_compensation)
		supabase.profiles.update.reset_mock()
		rollback_compensation()

		supabase.profiles.update.assert_called_once_with({"username": self.username})
		supabase.profiles.update.return_value.eq.assert_called_once_with(
			"id", self.auth_user_id
		)

	def test_username_change_failure_prevents_local_update(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			doc = self.make_app_user().insert()
			supabase.profiles.update.return_value.eq.return_value.execute.side_effect = (
				RuntimeError("Profile unavailable")
			)

			doc.username = "failed.change"
			with self.assertRaises(frappe.ValidationError):
				doc.save()

		doc.reload()
		self.assertEqual(doc.username, self.username)

	def test_reset_password_updates_only_supabase_auth(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			doc = self.make_app_user().insert()
			supabase.profiles.update.reset_mock()
			result = reset_app_user_password(doc.name, "new-secure-password")

		self.assertEqual(result, {"success": True})
		supabase.auth.admin.update_user_by_id.assert_called_once_with(
			self.auth_user_id,
			{"password": "new-secure-password"},
		)
		supabase.profiles.update.assert_not_called()
		doc.reload()
		self.assertIsNone(doc.password)
		self.assertIsNone(doc.get_password(raise_exception=False))

	def test_reset_password_rejects_short_value_before_supabase_call(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			doc = self.make_app_user().insert()
			supabase.auth.admin.update_user_by_id.reset_mock()
			with self.assertRaises(frappe.ValidationError):
				reset_app_user_password(doc.name, "short")

		supabase.auth.admin.update_user_by_id.assert_not_called()

	def test_disable_and_enable_user_updates_auth_profile_and_local_status(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			doc = self.make_app_user().insert()
			supabase.profiles.update.reset_mock()
			supabase.auth.admin.update_user_by_id.reset_mock()

			disable_result = set_app_user_enabled(doc.name, False)
			self.assertEqual(disable_result, {"status": "Inactive"})
			supabase.auth.admin.update_user_by_id.assert_called_once_with(
				self.auth_user_id,
				{"ban_duration": DISABLED_AUTH_BAN_DURATION},
			)
			supabase.profiles.update.assert_called_once_with({"status": "Inactive"})
			doc.reload()
			self.assertEqual(doc.status, "Inactive")

			supabase.profiles.update.reset_mock()
			supabase.auth.admin.update_user_by_id.reset_mock()
			enable_result = set_app_user_enabled(doc.name, True)

		self.assertEqual(enable_result, {"status": "Active"})
		supabase.auth.admin.update_user_by_id.assert_called_once_with(
			self.auth_user_id,
			{"ban_duration": "none"},
		)
		supabase.profiles.update.assert_called_once_with({"status": "Active"})
		doc.reload()
		self.assertEqual(doc.status, "Active")

	def test_synthetic_auth_email_is_not_stored_in_profile(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			self.make_app_user(email_address=None).insert()

		profile_payload = supabase.profiles.update.call_args.args[0]
		self.assertIsNone(profile_payload["email"])
		self.assertNotEqual(
			profile_payload["email"],
			f"{self.username}@dsku.invalid",
		)

	def test_requires_full_name_before_calling_supabase(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			with self.assertRaises(frappe.MandatoryError):
				self.make_app_user(full_name=None).insert()

		supabase.auth.admin.create_user.assert_not_called()

	def test_requires_password_before_calling_supabase(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			with self.assertRaises(frappe.MandatoryError):
				self.make_app_user(password=None).insert()

		supabase.auth.admin.create_user.assert_not_called()

	def test_requires_phone_before_calling_supabase(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			with self.assertRaises(frappe.MandatoryError):
				self.make_app_user(phone_number=None).insert()

		supabase.auth.admin.create_user.assert_not_called()

	def test_rejects_invalid_username_before_calling_supabase(self):
		supabase = self.make_supabase()

		for username in ("ab", "invalid@", "bad username", ".starts-with-dot"):
			with self.subTest(username=username):
				with patch(self.INIT_SUPABASE, return_value=supabase):
					with self.assertRaises(frappe.ValidationError):
						self.make_app_user(username=username).insert()

		supabase.auth.admin.create_user.assert_not_called()

	def test_rejects_normalized_username_duplicate_before_second_supabase_call(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			self.make_app_user(username="Duplicate.User").insert()
			with self.assertRaises(frappe.ValidationError):
				self.make_app_user(username="duplicate.user").insert()

		supabase.auth.admin.create_user.assert_called_once()

	def test_rejects_local_phone_duplicate_before_second_supabase_call(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			self.make_app_user(phone_number=self.local_phone).insert()
			with self.assertRaises(frappe.ValidationError):
				self.make_app_user(
					username=f"another-{uuid4().hex[:8]}",
					phone_number=self.e164_phone,
				).insert()

		supabase.auth.admin.create_user.assert_called_once()

	def test_supabase_failure_prevents_local_insert(self):
		supabase = self.make_supabase()
		supabase.auth.admin.create_user.side_effect = RuntimeError("Supabase unavailable")

		with patch(self.INIT_SUPABASE, return_value=supabase):
			with self.assertRaises(frappe.ValidationError):
				self.make_app_user().insert()

		self.assertFalse(frappe.db.exists("App User", {"username": self.username}))

	def test_invalid_supabase_user_id_prevents_local_insert(self):
		supabase = self.make_supabase(user_id="not-a-uuid")

		with patch(self.INIT_SUPABASE, return_value=supabase):
			with self.assertRaises(frappe.ValidationError):
				self.make_app_user().insert()

		self.assertFalse(frappe.db.exists("App User", {"username": self.username}))

	def test_profile_failure_deletes_new_auth_user(self):
		supabase = self.make_supabase()
		supabase.profiles.update.return_value.eq.return_value.execute.side_effect = RuntimeError(
			"Profile unavailable"
		)

		with patch(self.INIT_SUPABASE, return_value=supabase):
			with self.assertRaises(frappe.ValidationError):
				self.make_app_user().insert()

		supabase.auth.admin.delete_user.assert_called_once_with(self.auth_user_id)
		self.assertFalse(frappe.db.exists("App User", {"username": self.username}))

	def test_rollback_deletes_provisioned_supabase_user(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			self.make_app_user().insert()

		supabase.auth.admin.delete_user.assert_not_called()
		frappe.db.rollback()
		supabase.auth.admin.delete_user.assert_called_once_with(self.auth_user_id)
		supabase.profiles.delete.return_value.eq.assert_called_once_with(
			"id", self.auth_user_id
		)
