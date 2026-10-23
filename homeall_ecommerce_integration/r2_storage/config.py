import math
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import frappe


def fail(message):
	frappe.throw(frappe._(message), title=frappe._("R2 image storage"))


def boolean(value, name):
	if value in (True, 1, "1"):
		return True
	if value in (False, 0, "0", None):
		return False
	fail(f"{name} must be a JSON boolean or 0/1.")


def safe_path(value, name, empty=False):
	if not isinstance(value, str) or (not value and not empty):
		fail(f"{name} must be a relative folder path.")
	if value and any(not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in value.split("/")):
		fail(f"{name} must contain only folder names separated by single slashes.")
	return value


@dataclass(frozen=True)
class R2Config:
	account_id: str = field(repr=False)
	access_key_id: str = field(repr=False)
	secret_access_key: str = field(repr=False)
	bucket: str
	public_url: str
	prefix: str
	max_bytes: int
	delete_on_file_delete: bool
	optimize_images: bool = False
	optimize_threshold_bytes: int = 1024 * 1024
	optimize_target_bytes: int = 300 * 1024
	optimize_max_dimension: int = 1600
	optimize_quality: int = 82


def settings():
	"""Use the grouped configuration exclusively when present; accept legacy sites."""
	if "r2_storage" in frappe.conf:
		if not isinstance(frappe.conf.get("r2_storage"), dict):
			fail("r2_storage must be a JSON object.")
		return frappe.conf.get("r2_storage")
	return {key.removeprefix("r2_"): value for key, value in frappe.conf.items() if key.startswith("r2_")}


def setting(name, default=None):
	return settings().get(name, default)


def enabled():
	return boolean(setting("enabled"), "r2_storage.enabled")


def required(name):
	# Avoid retaining credential strings in validation traceback locals.
	key = f"r2_storage.{name}"
	if (
		not isinstance(setting(name), str)
		or not setting(name).strip()
		or setting(name) != setting(name).strip()
	):
		fail(f"{key} is required and must not contain surrounding whitespace.")
	return setting(name)


def size_setting(name, default, multiplier):
	try:
		value = setting(name, default)
		number = float(value)
		if isinstance(value, bool) or not math.isfinite(number) or number * multiplier < 1:
			raise ValueError
		return int(number * multiplier)
	except ValueError, TypeError, OverflowError:
		fail(f"r2_storage.{name} must be a positive finite size of at least one byte.")


def integer_setting(name, default, minimum, maximum):
	value = setting(name, default)
	try:
		number = int(value)
		if isinstance(value, bool) or float(value) != number or not minimum <= number <= maximum:
			raise ValueError
	except ValueError, TypeError, OverflowError:
		fail(f"r2_storage.{name} must be an integer between {minimum} and {maximum}.")
	return number


def get_config():
	if not enabled():
		return None
	values = {}
	for name in ("account_id", "bucket", "public_url"):
		values[name] = required(name)
	if not re.fullmatch(r"[a-fA-F0-9]{32}", values["account_id"]):
		fail("r2_storage.account_id must be the 32-character Cloudflare account ID.")
	if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", values["bucket"]):
		fail("r2_storage.bucket must be a valid bucket name.")
	try:
		url = urlsplit(values["public_url"])
		valid_url = (
			url.scheme == "https"
			and url.hostname
			and not (url.username or url.password or url.query or url.fragment or url.port not in (None, 443))
		)
	except ValueError:
		valid_url = False
	if not valid_url or any(c.isspace() for c in values["public_url"]):
		fail("r2_storage.public_url must be an HTTPS public URL without credentials, query, or fragment.")
	values["public_url"] = values["public_url"].rstrip("/")
	values["prefix"] = safe_path(setting("key_prefix", ""), "r2_storage.key_prefix", empty=True)
	try:
		limit = float(setting("max_file_size_mb", 10))
		if not math.isfinite(limit) or limit <= 0:
			raise ValueError
		values["max_bytes"] = int(limit * 1024 * 1024)
	except ValueError, TypeError, OverflowError:
		fail("r2_storage.max_file_size_mb must be a positive finite number.")
	values["delete_on_file_delete"] = boolean(
		setting("delete_on_file_delete", False), "r2_storage.delete_on_file_delete"
	)
	values["optimize_images"] = boolean(setting("optimize_images", False), "r2_storage.optimize_images")
	if values["optimize_images"]:
		values["optimize_threshold_bytes"] = size_setting("optimize_threshold_mb", 1, 1024 * 1024)
		values["optimize_target_bytes"] = size_setting("optimize_target_kb", 300, 1024)
		values["optimize_max_dimension"] = integer_setting("optimize_max_dimension", 1600, 128, 8192)
		values["optimize_quality"] = integer_setting("optimize_quality", 82, 50, 95)
	return R2Config(
		**values,
		access_key_id=required("access_key_id"),
		secret_access_key=required("secret_access_key"),
	)


def doctype_folder(doctype):
	settings = frappe.get_hooks("r2_upload_doctypes", {}).get(doctype)
	if not settings:
		return None
	folder = settings.get("folder")
	# Frappe merges scalar hook dictionary values into lists.
	if isinstance(folder, list):
		folder = folder[-1] if folder else None
	return safe_path(folder, "r2_upload_doctypes folder")
