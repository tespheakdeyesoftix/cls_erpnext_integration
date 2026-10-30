# Copyright (c) 2026, Tes Pheakdey and Contributors
# See license.txt

"""Offline lifecycle checks; Supabase is mocked and no live ads are changed."""

import json
import unittest
from copy import deepcopy
from unittest.mock import MagicMock, patch

import frappe

from homeall_ecommerce_integration.homeall_ecommerce_integration.doctype.app_open_ads import (
	app_open_ads as ads,
)


class TestAppOpenAds(unittest.TestCase):
	def setUp(self):
		self.doc = frappe._dict(
			name="55555555-5555-4555-8555-555555555555",
			docstatus=0,
			check_permission=MagicMock(),
			name1="Wholesale launch promotion",
			app_targets="Both",
			starts_at="2026-10-30 09:00:00",
			ends_at="2026-11-01 18:00:00",
			priority=10,
			display_seconds=5,
			skip_delay_second=0,
			frequency="once_per_day",
			photo="https://example.com/ad.jpg",
			action_type="deeplink",
			action_url="homeall://categories",
			action_open_in="webview",
		)
		self.client = MagicMock()
		for patcher in (
			patch.object(ads, "init_supabase", return_value=self.client),
			patch.object(ads, "get_system_timezone", return_value="Asia/Phnom_Penh"),
			patch.object(ads, "_", side_effect=lambda message: message),
			patch.object(frappe, "throw", side_effect=frappe.ValidationError),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def update_ad(self, doc=None):
		doc = doc if doc is not None else self.doc
		with patch.object(frappe, "get_doc", return_value=doc):
			return ads.publish_to_supabase(doc.name)

	def unpublish_ad(self, doc=None):
		doc = doc if doc is not None else self.doc
		with patch.object(frappe, "get_doc", return_value=doc):
			return ads.unpublish_to_supabase(doc.name)

	def test_manual_update_publishes_ad_using_document_uuid(self):
		self.update_ad()
		self.client.table.assert_called_once_with("app_open_ads")
		upsert = self.client.table.return_value.upsert
		payload = upsert.call_args.args[0]
		self.assertEqual(upsert.call_args.kwargs, {"on_conflict": "id"})
		self.assertEqual(payload["id"], self.doc.name)
		self.assertEqual(payload["name"], self.doc.name1)
		self.assertEqual(payload["status"], "published")
		self.assertEqual(payload["app_targets"], ["HomeAll", "DSKU"])
		self.assertEqual(payload["skip_delay_seconds"], 0)
		self.assertEqual(payload["background_color"], "#000000")
		self.assertEqual(payload["action_url"], "homeall://categories")
		self.assertIsNone(payload["action_open_in"])
		self.assertEqual(payload["starts_at"], "2026-10-30T09:00:00+07:00")
		self.assertEqual(payload["ends_at"], "2026-11-01T18:00:00+07:00")
		self.assertEqual(payload["artwork"]["en"]["image_url"], self.doc.photo)
		upsert.return_value.execute.assert_called_once_with()

	def test_single_app_targets_and_custom_background(self):
		self.doc.background_color = "#112233"
		for target, expected in (("HomeAll", ["HomeAll"]), ("DSKU", ["DSKU"])):
			with self.subTest(target=target):
				self.doc.app_targets = target
				payload = ads.prepare_record(self.doc)
				self.assertEqual(payload["app_targets"], expected)
				self.assertEqual(payload["background_color"], "#112233")

	def test_save_validates_and_generates_artwork_without_syncing(self):
		ads.AppOpenAds.validate(self.doc)
		artwork = json.loads(self.doc.artwork)
		self.assertEqual(artwork["en"]["image_url"], self.doc.photo)
		self.assertEqual(artwork["en"]["accessibility_text"], self.doc.name1)
		self.assertEqual(artwork["km"], {})
		self.assertEqual(artwork["zh"], {})
		self.client.table.assert_not_called()

	def test_save_preserves_custom_artwork_without_syncing(self):
		self.doc.artwork = json.dumps(
			{"en": {"image_url": "https://example.com/custom.jpg", "title": "Sale"}}
		)
		original = self.doc.artwork
		ads.AppOpenAds.validate(self.doc)
		self.assertEqual(self.doc.artwork, original)
		self.client.table.assert_not_called()

	def test_manual_update_loads_saved_ad_and_uses_validated_payload(self):
		with patch.object(frappe, "get_doc", return_value=self.doc) as get_doc:
			result = ads.publish_to_supabase(self.doc.name)
		get_doc.assert_called_once_with("App Open Ads", self.doc.name, for_update=True)
		self.doc.check_permission.assert_called_once_with("write")
		self.assertEqual(result, {"success": True, "id": self.doc.name})
		self.client.table.assert_called_once_with("app_open_ads")
		upsert = self.client.table.return_value.upsert
		self.assertEqual(upsert.call_args.args[0], ads.prepare_record(self.doc))
		self.assertEqual(upsert.call_args.kwargs, {"on_conflict": "id"})
		upsert.return_value.execute.assert_called_once_with()

	def test_manual_update_rejects_submitted_and_cancelled_ads(self):
		for docstatus in (1, 2):
			with self.subTest(docstatus=docstatus):
				self.doc.docstatus = docstatus
				with patch.object(frappe, "get_doc", return_value=self.doc):
					with self.assertRaises(frappe.ValidationError):
						ads.publish_to_supabase(self.doc.name)
		self.client.table.assert_not_called()

	def test_manual_update_requires_write_permission(self):
		self.doc.check_permission = MagicMock(side_effect=frappe.PermissionError)
		with patch.object(frappe, "get_doc", return_value=self.doc):
			with self.assertRaises(frappe.PermissionError):
				ads.publish_to_supabase(self.doc.name)
		self.client.table.assert_not_called()

	def test_localized_artwork_overrides_photo_and_preserves_content(self):
		artwork = {
			"en": {"image_url": "https://example.com/en.jpg", "title": "Sale", "cta_label": "Shop"},
			"km": {"image_url": "https://example.com/km.jpg", "accessibility_text": "Khmer ad"},
			"zh": {},
		}
		for value in (artwork, json.dumps(artwork)):
			with self.subTest(value_type=type(value)):
				self.doc.artwork = value
				original = deepcopy(value)
				payload = ads.prepare_record(self.doc)
				self.assertEqual(payload["artwork"]["en"]["image_url"], artwork["en"]["image_url"])
				self.assertEqual(payload["artwork"]["en"]["cta_label"], "Shop")
				self.assertEqual(payload["artwork"]["km"], artwork["km"])
				self.assertEqual(self.doc.artwork, original)

	def test_attached_public_photo_gets_absolute_url(self):
		self.doc.photo = "/files/ad.jpg"
		with patch.object(ads, "get_url", return_value="https://erp.example.com/files/ad.jpg") as get_url:
			payload = ads.prepare_record(self.doc)
		self.assertEqual(payload["artwork"]["en"]["image_url"], "https://erp.example.com/files/ad.jpg")
		get_url.assert_called_once_with("/files/ad.jpg")

	def test_invalid_ad_is_rejected_before_supabase_is_called(self):
		for changes in (
			{"app_targets": ""},
			{"name": "not-a-uuid"},
			{"starts_at": None},
			{"ends_at": "2026-10-30 08:00:00"},
			{"display_seconds": 0},
			{"skip_delay_second": -1},
			{"skip_delay_second": 6},
			{"artwork": "not json"},
			{"artwork": "[]"},
			{"artwork": []},
			{"artwork": '{"en": null}'},
			{"photo": None},
			{"photo": "/private/files/ad.jpg"},
			{"photo": "https://example.com/private/files/ad.jpg"},
			{"artwork": '{"en": {"image_url": 123}}'},
		):
			with self.subTest(changes=changes):
				doc = frappe._dict(self.doc.copy())
				doc.update(changes)
				with self.assertRaises(frappe.ValidationError):
					ads.AppOpenAds.validate(doc)
				with self.assertRaises(frappe.ValidationError):
					self.update_ad(doc)
		self.client.table.assert_not_called()

	def test_retry_upserts_same_uuid(self):
		self.update_ad()
		self.update_ad()
		calls = self.client.table.return_value.upsert.call_args_list
		self.assertEqual(calls[0], calls[1])

	def test_missing_action_url_is_rejected_before_supabase_is_called(self):
		for action_type in ("deeplink", "web"):
			for action_url in (None, "", "   "):
				with self.subTest(action_type=action_type, action_url=action_url):
					self.doc.update(action_type=action_type, action_url=action_url)
					with self.assertRaises(frappe.ValidationError):
						self.update_ad()
		self.client.table.assert_not_called()

	def test_action_url_is_trimmed_and_preserved_for_supported_actions(self):
		for action_type, action_url, open_in, expected_open_in in (
			("deeplink", "homeall://category?id=ba02e695-867a-4b99-89c0-97fa86e767fd", "webview", None),
			("deeplink", "homeall://categories", "external_browser", None),
			("deeplink", "homeall://categories", None, None),
			("web", "https://example.com/promotion", "webview", "webview"),
			("web", "https://example.com/promotion", "external_browser", "external_browser"),
			("web", "https://example.com/promotion", None, "webview"),
		):
			with self.subTest(action_type=action_type, open_in=open_in):
				self.doc.update(
					action_type=action_type, action_url=f"  {action_url}  ", action_open_in=open_in
				)
				payload = ads.prepare_record(self.doc)
				self.assertEqual(payload["action_type"], action_type)
				self.assertEqual(payload["action_url"], action_url)
				self.assertEqual(json.loads(json.dumps(payload))["action_open_in"], expected_open_in)

	def test_invalid_action_is_rejected_before_supabase_is_called(self):
		for action_type, action_url in (
			("unknown", "homeall://categories"),
			("deeplink", "categories"),
			("web", "homeall://categories"),
			("web", "https:///categories"),
		):
			with self.subTest(action_type=action_type, action_url=action_url):
				self.doc.update(action_type=action_type, action_url=action_url)
				with self.assertRaises(frappe.ValidationError):
					self.update_ad()
		self.client.table.assert_not_called()

	def test_trash_deletes_only_matching_uuid_without_validating_old_content(self):
		self.doc.artwork = "invalid old content"
		self.doc.photo = None
		ads.AppOpenAds.on_trash(self.doc)
		self.client.table.assert_called_once_with("app_open_ads")
		delete = self.client.table.return_value.delete
		delete.assert_called_once_with()
		delete.return_value.eq.assert_called_once_with("id", self.doc.name)
		delete.return_value.eq.return_value.execute.assert_called_once_with()
		self.client.table.return_value.upsert.assert_not_called()

	def test_trash_rejects_invalid_uuid_before_requesting_delete(self):
		self.doc.name = ""
		with self.assertRaises(frappe.ValidationError):
			ads.AppOpenAds.on_trash(self.doc)
		self.client.table.assert_not_called()

	def test_unpublish_only_sets_remote_status_to_draft_and_keeps_erp_document(self):
		self.doc.artwork = "invalid old content"
		self.doc.photo = None
		original = dict(self.doc)
		with (
			patch.object(frappe, "get_doc", return_value=self.doc) as get_doc,
			patch.object(frappe, "delete_doc") as delete_doc,
		):
			result = ads.unpublish_to_supabase(self.doc.name)
		get_doc.assert_called_once_with("App Open Ads", self.doc.name, for_update=True)
		self.doc.check_permission.assert_called_once_with("write")
		self.assertEqual(result, {"success": True, "id": self.doc.name})
		self.assertEqual(dict(self.doc), original)
		delete_doc.assert_not_called()
		self.client.table.assert_called_once_with("app_open_ads")
		update = self.client.table.return_value.update
		update.assert_called_once_with({"status": "draft"})
		update.return_value.eq.assert_called_once_with("id", self.doc.name)
		update.return_value.eq.return_value.execute.assert_called_once_with()
		self.client.table.return_value.delete.assert_not_called()
		self.client.table.return_value.upsert.assert_not_called()

	def test_unpublish_requires_write_permission(self):
		self.doc.check_permission = MagicMock(side_effect=frappe.PermissionError)
		with self.assertRaises(frappe.PermissionError):
			self.unpublish_ad()
		self.client.table.assert_not_called()

	def test_unpublish_rejects_invalid_uuid(self):
		self.doc.name = "invalid"
		with self.assertRaises(frappe.ValidationError):
			self.unpublish_ad()
		self.client.table.assert_not_called()

	def test_supabase_errors_propagate_so_publish_unpublish_and_trash_can_be_retried(self):
		for method, query in (
			(self.update_ad, self.client.table.return_value.upsert.return_value),
			(self.unpublish_ad, self.client.table.return_value.update.return_value.eq.return_value),
			(ads.AppOpenAds.on_trash, self.client.table.return_value.delete.return_value.eq.return_value),
		):
			with self.subTest(method=method.__name__):
				query.execute.side_effect = RuntimeError("offline")
				with patch.object(ads, "_log_sync_error") as log_error:
					with self.assertRaisesRegex(RuntimeError, "offline"):
						method(self.doc)
				log_error.assert_called_once()
