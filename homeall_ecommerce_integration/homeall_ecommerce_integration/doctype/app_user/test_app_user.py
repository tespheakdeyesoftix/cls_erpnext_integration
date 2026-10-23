# Copyright (c) 2026, Tes Pheakdey and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from supabase_auth.errors import AuthApiError

from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_user.app_user import (
	DISABLED_AUTH_BAN_DURATION,
	PROFILE_FIELD_MAP,
	AppUser,
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


class UnitTestAppUserCreationErrors(UnitTestCase):
	def assert_creation_error(self, error, expected_message):
		# Isolate the Auth failure from the local validation and database setup.
		doc = MagicMock()
		doc.username = "test.user"
		doc.phone_number = "+85512345678"
		doc.full_name = "Test User"
		doc.name = None
		doc.get.return_value = "a-secure-password"
		supabase = MagicMock()
		supabase.auth.admin.create_user.side_effect = error

		with (
			patch(f"{AppUser.__module__}.init_supabase", return_value=supabase),
			patch("frappe.log_error") as log_error,
		):
			with self.assertRaises(frappe.ValidationError) as raised:
				AppUser.before_insert(doc)

		self.assertIn(expected_message, str(raised.exception))
		self.assertNotIn(str(error), str(raised.exception))
		self.assertNotIn(str(error), log_error.call_args.kwargs["message"])
		supabase.auth.admin.create_user.assert_called_once()
		supabase.table.assert_not_called()
		supabase.auth.admin.delete_user.assert_not_called()
		self.assertIsNone(doc.name)

	def test_duplicate_auth_identity_explains_the_conflicting_field(self):
		for code, expected_message in (
			("phone_exists", "This phone number is already registered in Supabase Auth."),
			("email_exists", "This username is already registered in Supabase Auth."),
			("user_already_exists", "An account with this username or phone number already exists"),
		):
			with self.subTest(code=code):
				self.assert_creation_error(
					AuthApiError("Private Auth response", status=422, code=code),
					expected_message,
				)

	def test_unknown_auth_error_keeps_the_generic_message(self):
		self.assert_creation_error(
			AuthApiError("Private Auth response", status=500, code="unexpected_failure"),
			"Could not create the Supabase Auth user. Please try again.",
		)

	def test_unexpected_exception_keeps_the_generic_message(self):
		self.assert_creation_error(
			RuntimeError("Private connection details"),
			"Could not create the Supabase Auth user. Please try again.",
		)


class UnitTestAppUserProfileSync(UnitTestCase):
	def setUp(self):
		self.user_id = str(uuid4())
		self.values = {
			"username": "test.user",
			"full_name": "Test User",
			"email_address": "contact@example.com",
			"party": "Customer One",
			"is_dsku_user": 1,
			"default_price_list": "Selling",
			"user_type": str(uuid4()),
		}
		self.payload = {column: self.values[field] for field, column in PROFILE_FIELD_MAP.items()}
		self.payload.update(
			is_dsku_user=True, default_price_list_id=str(uuid4()), phone="+85512345678", status="Active"
		)
		self.doc = MagicMock()
		self.doc.name = self.user_id
		self.doc.username = self.values["username"]
		self.doc.flags = frappe._dict(in_insert=False)
		self.doc.get_doc_before_save.return_value = frappe._dict(self.values.copy())
		self.doc.get.side_effect = self.values.get
		self.doc._build_profile_payload.return_value = self.payload
		self.supabase = MagicMock()
		self.auth_user = SimpleNamespace(
			id=self.user_id,
			email="test.user@dsku.invalid",
			email_confirmed_at=True,
			user_metadata={"username": "test.user", "preferred_username": "test.user", "other": "preserved"},
		)
		self.supabase.auth.admin.get_user_by_id.return_value = SimpleNamespace(user=self.auth_user)

		def update_auth(user_id, values):
			if "email" in values:
				self.auth_user.email = values["email"]
			self.auth_user.user_metadata.update(values.get("user_metadata", {}))
			return SimpleNamespace(user=self.auth_user)

		self.supabase.auth.admin.update_user_by_id.side_effect = update_auth
		self.profiles = self.supabase.table.return_value
		self.remote_values = self.payload.copy()
		self.profiles.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
			SimpleNamespace(data=[self.remote_values])
		)
		self.profiles.update.return_value.eq.return_value.execute.return_value = SimpleNamespace(
			data=[{"id": self.user_id}]
		)
		self.db = MagicMock()
		self.addCleanup(patch.stopall)
		patch(f"{AppUser.__module__}.init_supabase", return_value=self.supabase).start()
		patch("frappe.db", self.db).start()
		patch("frappe.log_error").start()

	def test_each_editable_profile_field_syncs_without_a_username_change(self):
		for field, column in PROFILE_FIELD_MAP.items():
			with self.subTest(field=field):
				previous = frappe._dict(self.values.copy())
				previous[field] = None
				self.doc.get_doc_before_save.return_value = previous
				self.remote_values.update(self.payload)
				self.remote_values[column] = None
				self.profiles.update.reset_mock()

				AppUser.before_save(self.doc)

				changes = {column: self.payload[column]}
				self.profiles.update.assert_called_once_with(changes)
				self.profiles.update.return_value.eq.assert_called_once_with("id", self.user_id)
				self.doc._validate_remote_references.assert_called_with(self.supabase, changes)
		self.supabase.auth.admin.update_user_by_id.assert_not_called()

	def test_clearing_optional_fields_is_sent_to_supabase(self):
		changes = {
			"email": None,
			"erp_customer": None,
			"default_price_list_id": None,
			"user_type_id": None,
			"is_dsku_user": False,
		}
		for field, column in PROFILE_FIELD_MAP.items():
			if column in changes:
				self.values[field] = 0 if field == "is_dsku_user" else None
				self.payload[column] = changes[column]

		AppUser.before_save(self.doc)

		self.profiles.update.assert_called_once_with(changes)

	def test_rollback_restores_remote_values_even_when_erp_was_out_of_sync(self):
		self.values["full_name"] = "Updated Name"
		self.payload["full_name"] = "Updated Name"
		self.remote_values["full_name"] = "Remote Name"

		AppUser.before_save(self.doc)
		self.profiles.update.reset_mock()
		self.db.after_rollback.add.call_args.args[0]()

		self.profiles.update.assert_called_once_with({"full_name": "Remote Name"})

	def test_failed_update_raises_and_restores_the_remote_snapshot(self):
		self.values["full_name"] = "Updated Name"
		self.payload["full_name"] = "Updated Name"
		self.profiles.update.return_value.eq.return_value.execute.side_effect = [
			RuntimeError("Update response lost"),
			SimpleNamespace(data=[{"id": self.user_id}]),
		]

		with self.assertRaises(frappe.ValidationError):
			AppUser.before_save(self.doc)

		self.assertEqual(self.profiles.update.call_count, 2)
		self.assertEqual(self.profiles.update.call_args.args[0], {"full_name": "Test User"})

	def test_missing_profile_blocks_the_save_without_writing(self):
		self.values["full_name"] = "Updated Name"
		self.profiles.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
			SimpleNamespace(data=[])
		)

		with self.assertRaises(frappe.ValidationError):
			AppUser.before_save(self.doc)

		self.profiles.update.assert_not_called()

	def test_invalid_remote_reference_blocks_the_save_without_writing(self):
		self.values["user_type"] = str(uuid4())
		self.payload["user_type_id"] = self.values["user_type"]
		self.doc._validate_remote_references.side_effect = frappe.ValidationError("Missing user type")

		with self.assertRaises(frappe.ValidationError):
			AppUser.before_save(self.doc)

		self.profiles.update.assert_not_called()

	def test_unchanged_profile_skips_the_remote_update(self):
		AppUser.before_save(self.doc)

		self.profiles.update.assert_not_called()

	def test_saving_unchanged_erp_values_repairs_existing_remote_drift(self):
		self.remote_values.update(full_name="Outdated Name", erp_customer=None, user_type_id=None)

		AppUser.before_save(self.doc)

		self.profiles.update.assert_called_once_with(
			{
				"full_name": self.payload["full_name"],
				"erp_customer": self.payload["erp_customer"],
				"user_type_id": self.payload["user_type_id"],
			}
		)


	def change_username(self):
		self.values["username"] = "changed.user"
		self.doc.username = "changed.user"
		self.payload["username"] = "changed.user"

	def test_username_change_updates_auth_login_and_preserves_other_metadata(self):
		self.change_username()

		AppUser.before_save(self.doc)

		self.supabase.auth.admin.update_user_by_id.assert_called_once_with(
			self.user_id,
			{
				"email": "changed.user@dsku.invalid",
				"email_confirm": True,
				"user_metadata": {"username": "changed.user", "preferred_username": "changed.user"},
			},
		)
		self.assertEqual(self.auth_user.user_metadata["other"], "preserved")
		self.profiles.update.assert_called_once_with(
			{column: self.payload[column] for column in PROFILE_FIELD_MAP.values()}
		)

	def test_resaving_repairs_auth_even_when_profile_username_already_matches(self):
		self.auth_user.email = "old.user@dsku.invalid"
		self.auth_user.user_metadata.update(username="old.user", preferred_username="old.user")

		AppUser.before_save(self.doc)

		self.assertEqual(self.auth_user.email, "test.user@dsku.invalid")
		self.assertEqual(self.auth_user.user_metadata["username"], "test.user")
		self.profiles.update.assert_called_once()

	def test_profile_failure_restores_the_old_login_identity(self):
		self.change_username()
		self.profiles.update.return_value.eq.return_value.execute.side_effect = [
			RuntimeError("Profile unavailable"),
			SimpleNamespace(data=[{"id": self.user_id}]),
		]

		with self.assertRaises(frappe.ValidationError):
			AppUser.before_save(self.doc)

		self.assertEqual(self.auth_user.email, "test.user@dsku.invalid")
		self.assertEqual(self.auth_user.user_metadata["username"], "test.user")
		self.assertEqual(self.auth_user.user_metadata["other"], "preserved")

	def test_rollback_restores_both_auth_and_profile_username(self):
		self.change_username()
		AppUser.before_save(self.doc)
		self.profiles.update.reset_mock()

		self.db.after_rollback.add.call_args.args[0]()

		self.assertEqual(self.auth_user.email, "test.user@dsku.invalid")
		self.assertEqual(self.auth_user.user_metadata["preferred_username"], "test.user")
		self.assertEqual(self.profiles.update.call_args.args[0]["username"], "test.user")

	def test_auth_conflict_rejects_the_save_with_a_clear_message(self):
		self.change_username()
		self.supabase.auth.admin.update_user_by_id.side_effect = AuthApiError(
			"Email already exists", status=422, code="email_exists"
		)

		with self.assertRaisesRegex(frappe.ValidationError, "username is already registered"):
			AppUser.before_save(self.doc)

		self.assertEqual(self.auth_user.email, "test.user@dsku.invalid")

	def test_auth_read_failure_prevents_any_profile_update(self):
		self.supabase.auth.admin.get_user_by_id.side_effect = RuntimeError("Auth unavailable")

		with self.assertRaisesRegex(frappe.ValidationError, "Could not read the Supabase login"):
			AppUser.before_save(self.doc)

		self.profiles.update.assert_not_called()
		self.supabase.auth.admin.update_user_by_id.assert_not_called()


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
		auth_user = SimpleNamespace(
			id=user_id,
			email=f"{self.username}@dsku.invalid",
			email_confirmed_at=True,
			user_metadata={"username": self.username, "preferred_username": self.username},
		)
		supabase.auth.admin.get_user_by_id.return_value = SimpleNamespace(user=auth_user)

		def update_auth(user_id, values):
			if "email" in values:
				auth_user.email = values["email"]
			auth_user.user_metadata.update(values.get("user_metadata", {}))
			return SimpleNamespace(user=auth_user)

		supabase.auth.admin.update_user_by_id.side_effect = update_auth
		profiles = MagicMock()
		profiles.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
			SimpleNamespace(
				data=[
					{
						"id": user_id,
						"username": self.username,
						"full_name": "New User",
						"email": None,
						"erp_customer": None,
						"is_dsku_user": True,
						"default_price_list_id": None,
						"user_type_id": None,
					}
				]
			)
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

	def test_username_change_updates_supabase_profile_and_auth_login(self):
		supabase = self.make_supabase()

		with patch(self.INIT_SUPABASE, return_value=supabase):
			doc = self.make_app_user().insert()
			supabase.profiles.update.reset_mock()

			doc.username = " Changed.User "
			doc.save()

		self.assertEqual(doc.username, "changed.user")
		doc.reload()
		self.assertEqual(doc.username, "changed.user")
		self.assertEqual(supabase.profiles.update.call_args.args[0]["username"], "changed.user")
		supabase.profiles.update.return_value.eq.assert_called_once_with(
			"id", self.auth_user_id
		)
		supabase.auth.admin.create_user.assert_called_once()
		supabase.auth.admin.update_user_by_id.assert_called_once_with(
			self.auth_user_id,
			{
				"email": "changed.user@dsku.invalid",
				"email_confirm": True,
				"user_metadata": {"username": "changed.user", "preferred_username": "changed.user"},
			},
		)

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

		self.assertEqual(supabase.profiles.update.call_args.args[0]["username"], self.username)
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
