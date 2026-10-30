# Copyright (c) 2026, Tes Pheakdey and contributors
# For license information, please see license.txt

import json
from copy import deepcopy
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, get_system_timezone, get_url

from homeall_ecommerce_integration.controller import is_valid_uuid
from homeall_ecommerce_integration.homeall_ecommerce_integration.api.v1.fn_sync_to_supabase import (
	init_supabase,
)

APP_TARGETS = {"HomeAll": ["HomeAll"], "DSKU": ["DSKU"], "Both": ["HomeAll", "DSKU"]}


class AppOpenAds(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action_open_in: DF.Literal["webview", "external_browser"]
		action_type: DF.Literal["deeplink", "web"]
		action_url: DF.Data | None
		app_targets: DF.Literal["HomeAll", "DSKU", "Both"]
		artwork: DF.JSON | None
		display_mode: DF.Literal["fullscreen", "modal"]
		display_seconds: DF.Int
		ends_at: DF.Datetime
		frequency: DF.Literal["every_launch", "once_per_session", "once_per_day", "once_per_campaign"]
		name1: DF.Data
		note: DF.SmallText | None
		photo: DF.AttachImage | None
		priority: DF.Int
		skip_delay_second: DF.Int
		starts_at: DF.Datetime
	# end: auto-generated types

	def validate(self):
		if self.get("photo") and self.get("name1") and not _parse_artwork(self.get("artwork")):
			self.artwork = json.dumps(_artwork(self), ensure_ascii=False, indent=2)
		prepare_record(self)

	def on_trash(self):
		return _delete_ad(self)


@frappe.whitelist(methods=["POST"])
def publish_to_supabase(name: str):
	doc = frappe.get_doc("App Open Ads", name, for_update=True)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Only saved, non-submitted ads can be published to Supabase."))
	return _upsert_ad(doc)


@frappe.whitelist(methods=["POST"])
def unpublish_to_supabase(name: str):
	"""Set the app record to draft, preserving the Supabase row and ERP document."""
	doc = frappe.get_doc("App Open Ads", name, for_update=True)
	doc.check_permission("write")
	_validate_id(doc.name)
	try:
		init_supabase().table("app_open_ads").update({"status": "draft"}).eq("id", doc.name).execute()
	except Exception:
		_log_sync_error("unpublish", doc.name)
		raise
	return {"success": True, "id": doc.name}


def _delete_ad(doc):
	_validate_id(doc.name)
	try:
		init_supabase().table("app_open_ads").delete().eq("id", doc.name).execute()
	except Exception:
		_log_sync_error("delete", doc.name)
		raise
	return {"success": True, "id": doc.name}


def _upsert_ad(doc):
	payload = prepare_record(doc)
	try:
		init_supabase().table("app_open_ads").upsert(payload, on_conflict="id").execute()
	except Exception:
		_log_sync_error("sync", doc.name)
		raise
	return {"success": True, "id": doc.name}


def prepare_record(doc):
	"""Map the ERP document to the app schema, keeping its UUID stable for retries."""
	_validate_id(doc.name)
	if doc.get("app_targets") not in APP_TARGETS:
		frappe.throw(_("Select App Targets before saving the ad."))

	starts_at = _timestamp(doc.get("starts_at"))
	ends_at = _timestamp(doc.get("ends_at"))
	if ends_at <= starts_at:
		frappe.throw(_("Ends At must be after Starts At."))

	display_seconds = cint(doc.get("display_seconds"))
	skip_delay_seconds = cint(doc.get("skip_delay_second"))
	if display_seconds <= 0:
		frappe.throw(_("Display Seconds must be greater than zero."))
	if not 0 <= skip_delay_seconds <= display_seconds:
		frappe.throw(_("Skip Delay Second must be between zero and Display Seconds."))

	action_type = doc.get("action_type") or "deeplink"
	action_url = (doc.get("action_url") or "").strip()
	if action_type not in {"deeplink", "web"}:
		frappe.throw(_("Action Type must be deeplink or web."))
	if not action_url:
		frappe.throw(_("Action URL is required. Enter a deeplink such as homeall://categories or a web URL."))
	if action_type == "web":
		parsed = urlparse(action_url)
		if parsed.scheme not in {"http", "https"} or not parsed.netloc:
			frappe.throw(_("For a web action, Action URL must be a valid HTTP(S) URL."))
	elif not urlparse(action_url).scheme:
		frappe.throw(
			_("For a deeplink action, Action URL must include a scheme such as homeall://categories.")
		)

	return {
		"id": doc.name,
		"name": doc.get("name1"),
		"app_targets": APP_TARGETS[doc.app_targets].copy(),
		"status": "published",
		"starts_at": starts_at.isoformat(),
		"ends_at": ends_at.isoformat(),
		"priority": cint(doc.get("priority")),
		"display_mode": doc.get("display_mode") or "fullscreen",
		"display_seconds": display_seconds,
		"skip_delay_seconds": skip_delay_seconds,
		"frequency": doc.get("frequency") or "once_per_day",
		"background_color": doc.get("background_color") or "#000000",
		"artwork": _artwork(doc),
		"action_type": action_type,
		"action_url": action_url,
		"action_open_in": (doc.get("action_open_in") or "webview") if action_type == "web" else None,
	}


def _validate_id(name):
	if not is_valid_uuid(name):
		frappe.throw(_("The App Open Ads name must be a valid UUID."))


def _timestamp(value):
	if not value:
		frappe.throw(_("Starts At and Ends At are required before saving the ad."))
	timestamp = get_datetime(value)
	if timestamp.tzinfo is None:
		timestamp = timestamp.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return timestamp


def _parse_artwork(artwork):
	if artwork is None or (isinstance(artwork, str) and not artwork.strip()):
		return {}
	if isinstance(artwork, str):
		try:
			artwork = json.loads(artwork)
		except ValueError:
			frappe.throw(_("Artwork Medias must contain a valid JSON object."))
	if not isinstance(artwork, dict) or any(not isinstance(media, dict) for media in artwork.values()):
		frappe.throw(_("Artwork Medias must contain an object for each language."))
	return artwork


def _artwork(doc):
	artwork = deepcopy(_parse_artwork(doc.get("artwork")))
	for language in ("en", "km", "zh"):
		artwork.setdefault(language, {})
	english = artwork["en"]
	if not english.get("image_url") and doc.get("photo"):
		english["image_url"] = doc.photo
	english.setdefault("accessibility_text", doc.get("name1"))
	english.setdefault("title", None)
	english.setdefault("cta_label", None)

	has_image = False
	for media in artwork.values():
		if media.get("image_url"):
			media["image_url"] = _public_image_url(media["image_url"])
			has_image = True
	if not has_image:
		frappe.throw(_("Add a Photo or an image_url in Artwork Medias before saving the ad."))
	return artwork


def _public_image_url(value):
	if not isinstance(value, str):
		frappe.throw(_("Artwork image_url must be a public image URL."))
	value = value.strip()
	parsed = urlparse(value)
	if parsed.path.startswith("/private/"):
		frappe.throw(_("Ad images must be publicly accessible; private files are not supported."))
	if parsed.scheme in {"http", "https"} and parsed.netloc:
		return value
	if value.startswith("/files/"):
		return get_url(value)
	frappe.throw(_("Artwork image_url must be a public HTTP(S) URL or an attached public image."))


def _log_sync_error(action, name):
	frappe.log_error(
		title=f"App Open Ads Supabase {action} failed",
		message=f"App Open Ads: {name}\n\n{frappe.get_traceback()}",
	)
