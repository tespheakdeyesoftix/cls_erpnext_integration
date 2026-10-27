# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

import re

import frappe
import phonenumbers
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, validate_email_address
from phonenumbers import NumberParseException, PhoneNumberFormat

from homeall_ecommerce_integration.controller import is_valid_uuid
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.sync import init_supabase


DSKU_APP_KEY = "dsku-wholesale"
DSKU_AUTH_DOMAIN = "dsku.invalid"
DSKU_PASSWORD_METADATA_FIELD = "homeall_password_enabled"
DSKU_USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
ACTIVE_STATUS = "Active"
INACTIVE_STATUS = "Inactive"
# GoTrue accepts Go-style durations. This effectively disables the account until it is enabled again.
DISABLED_AUTH_BAN_DURATION = "876000h"
PROFILE_FIELD_MAP = {
	"username": "username",
	"full_name": "full_name",
	"email_address": "email",
	"party": "erp_customer",
	"is_dsku_user": "is_dsku_user",
	"default_price_list": "default_price_list_id",
	"user_type": "user_type_id",
}


def _normalize_username(username: str | None) -> str:
	username = (username or "").strip().lower()
	if not username:
		frappe.throw(_("Username is required."), exc=frappe.MandatoryError)

	if not DSKU_USERNAME_PATTERN.fullmatch(username):
		frappe.throw(
			_(
				"Username must be 3 to 32 lowercase characters and may contain only "
				"letters, numbers, periods, underscores, and hyphens."
			),
			exc=frappe.ValidationError,
		)

	return username


def _normalize_cambodian_phone(phone_number: str | None) -> str:
	phone_input = (phone_number or "").strip()
	if not phone_input:
		frappe.throw(_("Phone number is required."), exc=frappe.MandatoryError)

	if phone_input.startswith("855"):
		phone_input = f"+{phone_input}"

	try:
		phone = phonenumbers.parse(phone_input, "KH")
	except NumberParseException:
		phone = None

	if (
		not phone
		or not phonenumbers.is_valid_number(phone)
		or phonenumbers.region_code_for_number(phone) != "KH"
	):
		frappe.throw(
			_("Phone number must be a valid Cambodian phone number."),
			exc=frappe.ValidationError,
		)

	return phonenumbers.format_number(phone, PhoneNumberFormat.E164)


def _normalize_email(email_address: str | None) -> str | None:
	email_address = (email_address or "").strip().lower()
	if not email_address:
		return None

	validated_email = validate_email_address(email_address, throw=True)
	if not validated_email or "," in validated_email:
		frappe.throw(
			_("Email Address must contain exactly one valid email address."),
			exc=frappe.InvalidEmailAddressError,
		)

	return validated_email.lower()


def _log_supabase_error(title: str, operation: str, error: Exception) -> None:
	"""Log diagnostic context without recording credentials or request payloads."""
	error_code = getattr(error, "code", None)
	message = f"Operation: {operation}\nException type: {type(error).__name__}"
	if error_code:
		message += f"\nSupabase error code: {error_code}"

	frappe.log_error(
		title=title,
		message=message,
	)


def _update_profile(supabase, user_id: str, values: dict) -> None:
	response = (
		supabase.table("profiles")
		.update(values)
		.eq("id", user_id)
		.execute()
	)
	rows = response.data or []
	if len(rows) != 1 or str(rows[0].get("id")) != user_id:
		raise ValueError("Profile update did not return exactly one matching row")


def _restore_profile(supabase, user_id: str, values: dict) -> None:
	try:
		_update_profile(supabase, user_id, values)
	except Exception as error:
		_log_supabase_error(
			"Supabase App User Rollback Compensation Error",
			"restore profile fields",
			error,
		)


def _replace_user_item_groups(supabase, user_id: str, rows: list[dict]) -> None:
	supabase.table("user_item_groups").delete().eq("user_id", user_id).execute()
	if rows:
		supabase.table("user_item_groups").insert(rows).execute()


def _restore_user_item_groups(supabase, user_id: str, rows: list[dict]) -> None:
	try:
		_replace_user_item_groups(supabase, user_id, rows)
	except Exception as error:
		_log_supabase_error(
			"Supabase App User Rollback Compensation Error", "restore user item groups", error
		)


def _validate_supabase_user_response(response, user_id: str, operation: str) -> None:
	response_user_id = getattr(getattr(response, "user", None), "id", None)
	if str(response_user_id) != user_id:
		raise ValueError(f"Supabase {operation} did not return the matching Auth user")


def _auth_username_changes(supabase, user_id: str, username: str) -> tuple[dict, dict]:
	response = supabase.auth.admin.get_user_by_id(user_id)
	_validate_supabase_user_response(response, user_id, "username lookup")
	user = response.user
	metadata = user.user_metadata or {}
	changes = {}
	previous = {}
	email = f"{username}@{DSKU_AUTH_DOMAIN}"
	if user.email != email:
		changes.update(email=email, email_confirm=True)
		previous.update(email=user.email, email_confirm=bool(user.email_confirmed_at))
	metadata_changes = {
		field: username for field in ("username", "preferred_username") if metadata.get(field) != username
	}
	if metadata_changes:
		changes["user_metadata"] = metadata_changes
		previous["user_metadata"] = {field: metadata.get(field) for field in metadata_changes}
	return changes, previous


def _update_auth_username(supabase, user_id: str, values: dict) -> None:
	response = supabase.auth.admin.update_user_by_id(user_id, values)
	_validate_supabase_user_response(response, user_id, "username update")
	user = response.user
	if "email" in values and user.email != values["email"]:
		raise ValueError("Supabase did not apply the Auth login email")
	metadata = user.user_metadata or {}
	if any(metadata.get(field) != value for field, value in values.get("user_metadata", {}).items()):
		raise ValueError("Supabase did not apply the Auth username metadata")


def _restore_user_update(supabase, user_id: str, profile_values: dict, auth_values: dict) -> None:
	if auth_values:
		try:
			_update_auth_username(supabase, user_id, auth_values)
		except Exception as error:
			_log_supabase_error(
				"Supabase App User Rollback Compensation Error", "restore Auth username", error
			)
	# Auth triggers may update profiles, so restore the profile after Auth.
	if profile_values:
		_restore_profile(supabase, user_id, profile_values)


def _update_auth_enabled(supabase, user_id: str, enabled: bool) -> None:
	response = supabase.auth.admin.update_user_by_id(
		user_id,
		{"ban_duration": "none" if enabled else DISABLED_AUTH_BAN_DURATION},
	)
	_validate_supabase_user_response(response, user_id, "account status update")


def _update_profile_status(supabase, user_id: str, status: str) -> None:
	response = (
		supabase.table("profiles")
		.update({"status": status})
		.eq("id", user_id)
		.execute()
	)
	rows = response.data or []
	if len(rows) != 1 or str(rows[0].get("id")) != user_id:
		raise ValueError("Profile status update did not return exactly one matching row")


def _restore_account_status(supabase, user_id: str, status: str) -> None:
	enabled = status == ACTIVE_STATUS
	try:
		_update_auth_enabled(supabase, user_id, enabled)
	except Exception as error:
		_log_supabase_error(
			"Supabase App User Rollback Compensation Error",
			"restore Auth account status",
			error,
		)

	try:
		_update_profile_status(supabase, user_id, status)
	except Exception as error:
		_log_supabase_error(
			"Supabase App User Rollback Compensation Error",
			"restore profile status",
			error,
		)


def _get_app_user_for_admin_action(name: str) -> "AppUser":
	if not is_valid_uuid(name):
		frappe.throw(_("App User name must be a valid Supabase Auth UUID."))

	doc = frappe.get_doc("App User", name)
	doc.check_permission("write")
	return doc


@frappe.whitelist()
def reset_app_user_password(name: str, password: str) -> dict:
	doc = _get_app_user_for_admin_action(name)
	if not password:
		frappe.throw(_("New password is required."), exc=frappe.MandatoryError)
	if len(password) < 6:
		frappe.throw(_("New password must contain at least 6 characters."))

	supabase = init_supabase()
	try:
		response = supabase.auth.admin.update_user_by_id(doc.name, {"password": password})
		_validate_supabase_user_response(response, doc.name, "password reset")
	except Exception as error:
		_log_supabase_error(
			"Supabase App User Password Reset Error",
			"reset Auth password",
			error,
		)
		frappe.throw(
			_("Could not reset the Supabase user password. Please try again."),
			exc=frappe.ValidationError,
		)

	return {"success": True}


@frappe.whitelist()
def set_app_user_enabled(name: str, enabled: int | str | bool) -> dict:
	doc = _get_app_user_for_admin_action(name)
	enabled = bool(cint(enabled))
	new_status = ACTIVE_STATUS if enabled else INACTIVE_STATUS
	old_status = doc.status or ACTIVE_STATUS
	if old_status == new_status:
		return {"status": new_status}

	supabase = init_supabase()
	try:
		_update_auth_enabled(supabase, doc.name, enabled)
		_update_profile_status(supabase, doc.name, new_status)
	except Exception as error:
		_log_supabase_error(
			"Supabase App User Status Update Error",
			"update Auth and profile status",
			error,
		)
		_restore_account_status(supabase, doc.name, old_status)
		frappe.throw(
			_("Could not update the Supabase user account status. Please try again."),
			exc=frappe.ValidationError,
		)

	try:
		frappe.db.set_value("App User", doc.name, "status", new_status, update_modified=True)
	except Exception:
		_restore_account_status(supabase, doc.name, old_status)
		raise

	frappe.db.after_rollback.add(
		lambda supabase=supabase, user_id=doc.name, status=old_status: (
			_restore_account_status(supabase, user_id, status)
		)
	)
	return {"status": new_status}


class _SupabaseUserCleanup:
	def __init__(self, supabase, user_id: str):
		self.supabase = supabase
		self.user_id = user_id
		self.active = True

	def __call__(self) -> None:
		if not self.active:
			return

		cleanup_succeeded = True
		try:
			self.supabase.auth.admin.delete_user(self.user_id)
		except Exception as error:
			cleanup_succeeded = False
			_log_supabase_error(
				"Supabase App User Cleanup Error",
				"delete Auth user",
				error,
			)

		# This is harmless if deleting the Auth user already removed the profile by cascade.
		try:
			(
				self.supabase.table("profiles")
				.delete()
				.eq("id", self.user_id)
				.execute()
			)
		except Exception as error:
			cleanup_succeeded = False
			_log_supabase_error(
				"Supabase App User Cleanup Error",
				"delete profile",
				error,
			)

		if cleanup_succeeded:
			self.active = False


class AppUser(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_user_item_group.app_user_item_group import AppUserItemGroup

		allow_item_groups: DF.Table[AppUserItemGroup]
		default_price_list: DF.Link | None
		email_address: DF.Data | None
		full_name: DF.Data | None
		is_dsku_user: DF.Check
		is_homeall_user: DF.Check
		party: DF.Link | None
		password: DF.Password | None
		phone_number: DF.Data | None
		photo: DF.AttachImage | None
		status: DF.Literal["Active", "Inactive"]
		user_type: DF.Link | None
		username: DF.Data | None
	# end: auto-generated types

	_DOCTYPE_NAME = "App User"

	def before_insert(self) -> None:
		password = self.get("password")
		self._validate_creation_values(password)
		self._validate_unique_identity()
		self._build_item_group_payload()

		profile_payload = self._build_profile_payload()
		supabase = init_supabase()
		self._validate_remote_references(supabase, profile_payload)

		auth_payload = {
			"email": f"{self.username}@{DSKU_AUTH_DOMAIN}",
			"phone": self.phone_number,
			"password": password,
			"email_confirm": True,
			"phone_confirm": True,
			"user_metadata": {
				"full_name": self.full_name,
				"username": self.username,
				"preferred_username": self.username,
				"app_key": DSKU_APP_KEY,
				DSKU_PASSWORD_METADATA_FIELD: True,
			},
		}

		try:
			response = supabase.auth.admin.create_user(auth_payload)
		except Exception as error:
			_log_supabase_error(
				"Supabase App User Provisioning Error",
				"create Auth user",
				error,
			)
			# Auth can contain accounts that have not been imported into ERP.
			# Use known error codes rather than exposing the raw Auth response.
			error_messages = {
				"phone_exists": _(
					"This phone number is already registered in Supabase Auth. "
					"Use a different phone number or ask an administrator to locate the existing account."
				),
				"email_exists": _(
					"This username is already registered in Supabase Auth. "
					"Use a different username or ask an administrator to locate the existing account."
				),
				"user_already_exists": _(
					"An account with this username or phone number already exists in Supabase Auth. "
					"Use different details or ask an administrator to locate the existing account."
				),
			}
			frappe.throw(
				error_messages.get(
					getattr(error, "code", None),
					_("Could not create the Supabase Auth user. Please try again."),
				),
				exc=frappe.ValidationError,
			)

		user_id = getattr(getattr(response, "user", None), "id", None)
		if not is_valid_uuid(user_id):
			frappe.log_error(
				title="Supabase App User Provisioning Error",
				message="Supabase Auth did not return a valid user UUID.",
			)
			frappe.throw(
				_("Supabase did not return a valid user ID. The App User was not created."),
				exc=frappe.ValidationError,
			)

		user_id = str(user_id)
		cleanup = _SupabaseUserCleanup(supabase, user_id)
		frappe.db.after_rollback.add(cleanup)

		try:
			existing_profile_response = (
				supabase.table("profiles")
				.select("id")
				.eq("id", user_id)
				.limit(2)
				.execute()
			)
			existing_profile_rows = existing_profile_response.data or []
			if (
				len(existing_profile_rows) != 1
				or str(existing_profile_rows[0].get("id")) != user_id
			):
				raise ValueError("Auth trigger did not create exactly one matching profile")

			profile_response = (
				supabase.table("profiles")
				.update(profile_payload)
				.eq("id", user_id)
				.execute()
			)
			profile_rows = profile_response.data or []
			if len(profile_rows) != 1 or str(profile_rows[0].get("id")) != user_id:
				raise ValueError("Profile upsert did not return exactly one matching row")
		except Exception as error:
			_log_supabase_error(
				"Supabase App User Provisioning Error",
				"provision profile",
				error,
			)
			cleanup()
			frappe.throw(
				_("Could not provision the Supabase user profile. The Auth user was removed."),
				exc=frappe.ValidationError,
			)

		self.name = user_id
		self.password = None

	def validate(self) -> None:
		if self.name and not str(self.name).startswith("new-") and not is_valid_uuid(self.name):
			frappe.throw(_("App User name must be a valid Supabase Auth UUID."))

		self._build_item_group_payload()

		if self.is_new():
			return

		self.username = _normalize_username(self.username)
		self.email_address = _normalize_email(self.email_address)
		self.full_name = (self.full_name or "").strip()
		if not self.full_name:
			frappe.throw(_("Full Name is required."), exc=frappe.MandatoryError)
		if frappe.db.exists(
			"App User",
			{"username": self.username, "name": ["!=", self.name]},
		):
			frappe.throw(
				_("An App User with username {0} already exists.").format(
					frappe.bold(self.username)
				),
				exc=frappe.ValidationError,
			)

		previous = self.get_doc_before_save()
		if previous and previous.phone_number != self.phone_number:
			frappe.throw(
				_("Phone number cannot be changed until Auth identity synchronization is implemented.")
			)

		self.status = self.status or ACTIVE_STATUS
		if self.status not in (ACTIVE_STATUS, INACTIVE_STATUS):
			frappe.throw(_("Status must be Active or Inactive."))
		if previous and (previous.status or ACTIVE_STATUS) != self.status:
			frappe.throw(_("Use the Enable User or Disable User action to change account status."))

	def before_save(self) -> None:
		if self.flags.in_insert:
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		profile_payload = self._build_profile_payload()
		profile_values = {column: profile_payload[column] for column in PROFILE_FIELD_MAP.values()}
		supabase = init_supabase()

		# Restore the actual remote values if the local transaction later rolls back.
		try:
			response = (
				supabase.table("profiles")
				.select(",".join(profile_values))
				.eq("id", self.name)
				.limit(2)
				.execute()
			)
			rows = response.data or []
			if len(rows) != 1:
				raise ValueError("Profile snapshot did not return exactly one matching row")
			remote_values = {column: rows[0][column] for column in profile_values}
		except Exception as error:
			_log_supabase_error(
				"Supabase App User Update Error",
				"read profile before update",
				error,
			)
			frappe.throw(
				_("Could not read the Supabase user profile. The App User was not updated."),
				exc=frappe.ValidationError,
			)

		# A prior save may have persisted locally while the server ran older code.
		# Compare with Supabase so saving again also repairs that existing drift.
		changes = {column: value for column, value in profile_values.items() if value != remote_values[column]}
		try:
			auth_changes, previous_auth_values = _auth_username_changes(supabase, self.name, self.username)
		except Exception as error:
			_log_supabase_error("Supabase App User Update Error", "read Auth username before update", error)
			frappe.throw(_("Could not read the Supabase login account. The App User was not updated."))
		if not changes and not auth_changes:
			return
		if auth_changes:
			# Reapply ERP profile values after any Auth triggers have run.
			changes = profile_values
		self._validate_remote_references(supabase, changes)
		previous_values = {column: remote_values[column] for column in changes}
		frappe.db.after_rollback.add(
			lambda supabase=supabase, user_id=self.name, values=previous_values, auth=previous_auth_values: (
				_restore_user_update(supabase, user_id, values, auth)
			)
		)
		try:
			if auth_changes:
				_update_auth_username(supabase, self.name, auth_changes)
			_update_profile(supabase, self.name, changes)
		except Exception as error:
			_log_supabase_error(
				"Supabase App User Update Error",
				"update Auth username and profile fields",
				error,
			)
			_restore_user_update(supabase, self.name, previous_values, previous_auth_values)
			if getattr(error, "code", None) in ("email_exists", "user_already_exists"):
				frappe.throw(_("This username is already registered in Supabase Auth. Choose another username."))
			frappe.throw(
				_("Could not update the Supabase login account and profile. The App User was not updated."),
				exc=frappe.ValidationError,
			)

	def on_update(self) -> None:
		# Frappe calls on_update for both inserts and updates, including child-table-only edits.
		rows = self._build_item_group_payload()
		supabase = init_supabase()
		try:
			response = (
				supabase.table("user_item_groups")
				.select("user_id,item_group_id,include_all_descendant")
				.eq("user_id", self.name)
				.execute()
			)
			previous_rows = response.data or []
		except Exception as error:
			_log_supabase_error("Supabase App User Item Group Sync Error", "read user item groups", error)
			frappe.throw(
				_("Could not read the Supabase user item groups. The App User was not saved."),
				exc=frappe.ValidationError,
			)

		frappe.db.after_rollback.add(
			lambda supabase=supabase, user_id=self.name, rows=previous_rows: (
				_restore_user_item_groups(supabase, user_id, rows)
			)
		)
		try:
			_replace_user_item_groups(supabase, self.name, rows)
		except Exception as error:
			_log_supabase_error("Supabase App User Item Group Sync Error", "replace user item groups", error)
			_restore_user_item_groups(supabase, self.name, previous_rows)
			frappe.throw(
				_("Could not sync the Supabase user item groups. The App User was not saved."),
				exc=frappe.ValidationError,
			)

	def _build_item_group_payload(self) -> list[dict]:
		rows = []
		seen = set()
		for row in self.get("allow_item_groups") or []:
			if not row.item_group or not is_valid_uuid(row.supabase_id):
				frappe.throw(
					_("Row {0}: select an Item Group with a valid Supabase ID before saving the App User.").format(
						row.idx
					),
					exc=frappe.ValidationError,
				)
			item_group_id = str(row.supabase_id)
			if item_group_id in seen:
				frappe.throw(
					_("Row {0}: Item Group is assigned more than once.").format(row.idx),
					exc=frappe.ValidationError,
				)
			seen.add(item_group_id)
			rows.append(
				{
					"user_id": self.name,
					"item_group_id": item_group_id,
					"include_all_descendant": bool(cint(row.include_all_descendant)),
				}
			)
		return rows

	def before_rename(self, old_name: str, new_name: str, merge: bool = False) -> None:
		frappe.throw(_("App User cannot be renamed because its name is the Supabase Auth UUID."))

	def _validate_creation_values(self, password: str | None) -> None:
		if not password or self.is_dummy_password(password):
			frappe.throw(
				_("Password is required when creating an App User."),
				exc=frappe.MandatoryError,
			)

		self.username = _normalize_username(self.username)
		self.phone_number = _normalize_cambodian_phone(self.phone_number)
		self.email_address = _normalize_email(self.email_address)
		self.full_name = (self.full_name or "").strip()
		self.status = ACTIVE_STATUS
		if not self.full_name:
			frappe.throw(_("Full Name is required."), exc=frappe.MandatoryError)

	def _validate_unique_identity(self) -> None:
		if frappe.db.exists("App User", {"username": self.username}):
			frappe.throw(
				_("An App User with username {0} already exists.").format(frappe.bold(self.username)),
				exc=frappe.ValidationError,
			)

		if frappe.db.exists("App User", {"phone_number": self.phone_number}):
			frappe.throw(
				_("An App User with phone number {0} already exists.").format(
					frappe.bold(self.phone_number)
				),
				exc=frappe.ValidationError,
			)

	def _build_profile_payload(self) -> dict:
		return {
			"username": self.username,
			"full_name": self.full_name,
			"phone": self.phone_number,
			# Never copy the synthetic Auth email into the public profile.
			"email": self.email_address,
			"erp_customer": self.party or None,
			"is_dsku_user": bool(cint(self.is_dsku_user)),
			"default_price_list_id": self._get_price_list_id(),
			"user_type_id": self._get_user_type_id(),
			"status": self.status,
		}

	def _get_price_list_id(self) -> str | None:
		if not self.default_price_list:
			return None

		price_list_id = frappe.db.get_value(
			"Price List",
			self.default_price_list,
			"custom_supabase_id",
		)
		if not is_valid_uuid(price_list_id):
			frappe.throw(
				_("Default Price List must have a valid Supabase ID before saving the App User."),
				exc=frappe.ValidationError,
			)

		if frappe.db.count("Price List", {"custom_supabase_id": price_list_id}) != 1:
			frappe.throw(
				_("The Supabase ID for Default Price List is ambiguous."),
				exc=frappe.ValidationError,
			)

		return str(price_list_id)

	def _get_user_type_id(self) -> str | None:
		if not self.user_type:
			return None

		if not is_valid_uuid(self.user_type):
			frappe.throw(
				_("User Type must use a valid Supabase UUID."),
				exc=frappe.ValidationError,
			)

		return str(self.user_type)

	def _validate_remote_references(self, supabase, profile_payload: dict) -> None:
		references = (
			("price_lists", profile_payload.get("default_price_list_id"), _("Default Price List")),
			("user_types", profile_payload.get("user_type_id"), _("User Type")),
		)

		for table_name, record_id, label in references:
			if not record_id:
				continue

			try:
				response = (
					supabase.table(table_name)
					.select("id")
					.eq("id", record_id)
					.limit(2)
					.execute()
				)
			except Exception as error:
				_log_supabase_error(
					"Supabase App User Reference Validation Error",
					f"validate {table_name} reference",
					error,
				)
				frappe.throw(
					_("Could not validate {0} in Supabase. Please try again.").format(label),
					exc=frappe.ValidationError,
				)

			rows = response.data or []
			if len(rows) != 1 or str(rows[0].get("id")) != record_id:
				frappe.throw(
					_(
						"{0} does not have a matching Supabase record. "
						"Synchronize it first, then save the App User again."
					).format(label),
					exc=frappe.ValidationError,
				)
