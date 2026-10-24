"""Offline contract tests; no live messages, migrations or uploads are performed."""

import asyncio
import hashlib
import io
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from PIL import Image
from werkzeug.datastructures import Headers

from . import bridge, chat

ADMIN = "820b9613-7ba4-45fa-9fba-81652ef6a651"
CONVERSATION = "10000000-0000-4000-8000-000000000001"
CLIENT = "20000000-0000-4000-8000-000000000002"
MESSAGE = "30000000-0000-4000-8000-000000000003"
READY = {"aliases": True, "send_rpc": True, "frappe_send_rpc": True, "shared_send_rpc": True}


class Failure(Exception):
	pass


def fail(message, permission=False):
	raise Failure(message)


def raw(fn):
	return getattr(fn, "__wrapped__", fn)


class ChatTests(unittest.TestCase):
	def setUp(self):
		self.db = MagicMock()
		self.conf = frappe._dict(
			supabase_url="https://test.supabase.co",
			supabase_service_role_key="sb_secret_hidden",
			supabase_admin_user_id=ADMIN,
		)
		p = patch.object(chat, "http_session", return_value=chat.requests)
		p.start()
		self.addCleanup(p.stop)
		self.logger = MagicMock()
		p = patch.object(frappe, "logger", return_value=self.logger)
		p.start()
		self.addCleanup(p.stop)
		for target, value in [
			("conf", self.conf),
			("db", self.db),
			("session", frappe._dict(user="staff@example.com")),
		]:
			p = patch.object(frappe, target, value)
			p.start()
			self.addCleanup(p.stop)
		p = patch.object(chat, "fail", side_effect=fail)
		p.start()
		self.addCleanup(p.stop)
		self.db.get_value.return_value = frappe._dict(enabled=1, user_type="System User")

	def test_guest_and_disabled_and_website_users_denied(self):
		self.assertFalse(chat.allowed_user("Guest"))
		for info in [
			None,
			frappe._dict(enabled=0, user_type="System User"),
			frappe._dict(enabled=1, user_type="Website User"),
		]:
			self.db.get_value.return_value = info
			self.assertFalse(chat.allowed_user("staff@example.com"))

	def test_all_system_users_can_read_and_reply_roles_remain_separate(self):
		with patch.object(frappe, "get_roles", return_value=["Employee"]):
			self.assertTrue(chat.allowed_user("staff@example.com"))
			self.assertFalse(chat.allowed_user("staff@example.com", True))
		with patch.object(frappe, "get_roles", return_value=["System Manager"]):
			self.assertTrue(chat.allowed_user("staff@example.com", True))
		self.conf.chat_read_roles = ["Support Viewer"]
		self.conf.chat_reply_roles = ["Support Operator"]
		with patch.object(frappe, "get_roles", return_value=["Support Viewer"]):
			self.assertTrue(chat.allowed_user("staff@example.com"))
			self.assertFalse(chat.allowed_user("staff@example.com", True))

	def test_unauthorized_method_does_not_contact_supabase(self):
		self.db.get_value.return_value = frappe._dict(enabled=1, user_type="Website User")
		with patch.object(frappe, "get_roles", return_value=[]), patch.object(chat, "rpc") as rpc:
			with self.assertRaises(Failure):
				raw(chat.messages)(CONVERSATION)
			rpc.assert_not_called()

	def test_admin_profile_and_membership_must_be_active(self):
		for profiles, memberships in [
			([], []),
			([{"status": "Disabled"}], []),
			([{"status": "Active"}], [{"role": "owner", "status": "disabled"}]),
		]:
			with patch.object(chat, "request", side_effect=[profiles, memberships]):
				with self.assertRaises(Failure):
					chat.admin_role()
		with patch.object(
			chat, "request", side_effect=[[{"status": "Active"}], [{"role": "viewer", "status": "active"}]]
		):
			self.assertEqual(chat.admin_role(), {"viewer"})

	def test_supabase_viewer_is_read_only_and_rpc_rejection_is_preserved(self):
		with (
			patch.object(chat, "require_staff"),
			patch.object(chat, "admin_role", return_value={"viewer"}),
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "allowed_user", return_value=True),
			patch.object(chat, "bridge_health", return_value={}),
			patch.object(chat, "staff_name", return_value="Staff"),
		):
			self.assertFalse(raw(chat.bootstrap)()["can_send"])
			with patch.object(chat, "rpc", side_effect=Failure("Supabase membership is read-only")):
				with self.assertRaisesRegex(Failure, "read-only"):
					raw(chat.send_text)(CONVERSATION, CLIENT, "Hello")

	def test_secret_key_is_not_used_as_bearer_jwt(self):
		response = MagicMock(ok=True)
		response.json.return_value = {"items": []}
		with patch.object(chat.requests, "request", return_value=response) as request:
			chat.rpc("api_admin_chat_conversations", p_limit=50)
			self.assertEqual(request.call_args.kwargs["headers"], {"apikey": "sb_secret_hidden"})
			self.assertEqual(request.call_args.kwargs["json"]["p_user"], ADMIN)

	def test_supabase_error_never_returns_remote_details(self):
		response = MagicMock(ok=False, status_code=403)
		response.json.return_value = {"code": "42501", "message": "Denied sb_secret_hidden"}
		with patch.object(chat.requests, "request", return_value=response):
			with self.assertRaises(Failure) as error:
				chat.request("profiles")
		self.assertNotIn("sb_secret", str(error.exception))

	def test_cursors_require_timestamp_and_uuid_together(self):
		for cursor in [{"created_at": "2026-01-01"}, {"id": CLIENT}, {"created_at": "bad", "id": CLIENT}]:
			with self.assertRaises(Failure):
				chat.cursor_params(cursor)
		self.assertEqual(
			chat.cursor_params({"created_at": "2026-01-01T00:00:00Z", "id": CLIENT})["p_before_id"], CLIENT
		)

	def test_blank_and_oversized_text_rejected_before_rpc(self):
		with patch.object(chat, "authorize"), patch.object(chat, "save_message") as send:
			for body in [" ", "a" * 4001]:
				with self.assertRaises(Failure):
					raw(chat.send_text)(CONVERSATION, CLIENT, body)
			send.assert_not_called()

	def test_alias_is_server_derived_and_retries_keep_original_result(self):
		saved = {
			"id": MESSAGE,
			"conversation_id": CONVERSATION,
			"kind": "text",
			"sender_display_name": "Original Staff",
		}
		with (
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "rpc", return_value=saved) as rpc,
			patch.object(chat, "publish"),
		):
			for name in ["Original Staff", "Renamed Staff"]:
				self.db.get_value.return_value = name
				self.assertEqual(
					chat.save_message(CONVERSATION, CLIENT, "text", body="Hello")["sender_display_name"],
					"Original Staff",
				)
				self.assertEqual(rpc.call_args.kwargs["p_sender_display_name"], name)
				self.assertEqual(rpc.call_args.args[0], "api_frappe_admin_chat_send_message")
				self.assertEqual(rpc.call_args.kwargs["p_client_message"], CLIENT)
		self.db.get_value.return_value = None
		self.assertEqual(chat.staff_name(), "staff@example.com")

	def test_capabilities_require_the_new_rpc_and_all_its_named_parameters(self):
		cache = MagicMock()
		cache.get_value.return_value = None
		properties = {p: {"type": "string"} for p in chat.SEND_PARAMETERS - {"p_sender_display_name"}}
		schema = {
			"definitions": {"chat_messages": {"properties": {"sender_display_name": {"type": "string"}}}},
			"paths": {"/rpc/api_admin_chat_send_message": {"post": {"parameters": []}}},
		}
		with (
			patch.object(frappe, "cache", return_value=cache),
			patch.object(chat, "request", return_value=schema),
		):
			self.assertEqual(chat.capabilities(), {**READY, "send_rpc": False, "frappe_send_rpc": False})
			schema["paths"]["/rpc/api_frappe_admin_chat_send_message"] = {
				"post": {"parameters": [{"in": "body", "schema": {"properties": properties}}]}
			}
			self.assertEqual(chat.capabilities(), {**READY, "send_rpc": False})
			properties["p_sender_display_name"] = {"type": "string"}
			self.assertEqual(chat.capabilities(), READY)

	def test_setup_notice_distinguishes_missing_prerequisite_from_alias_support(self):
		self.assertIn(
			"20261003001900_business_chat.sql", chat.send_setup_notice({**READY, "shared_send_rpc": False})
		)
		self.assertIn(
			"20261023000100_frappe_chat_staff_alias.sql",
			chat.send_setup_notice({**READY, "frappe_send_rpc": False}),
		)
		self.assertIn("parameters", chat.send_setup_notice({**READY, "send_rpc": False}))
		self.assertIsNone(chat.send_setup_notice(READY))

	def test_display_name_is_trimmed_and_blank_names_fall_back_to_identifier(self):
		for name in [None, "", "   "]:
			self.db.get_value.return_value = name
			self.assertEqual(chat.staff_name(), "staff@example.com")
		self.db.get_value.return_value = "  Alice Staff  "
		self.assertEqual(chat.staff_name(), "Alice Staff")
		self.db.get_value.return_value = "a" * 256
		with self.assertRaisesRegex(Failure, "1-255"):
			chat.staff_name()

	def test_invalid_configured_admin_has_a_clear_configuration_error(self):
		self.conf.supabase_admin_user_id = "invalid"
		with self.assertRaisesRegex(Failure, "supabase_admin_user_id"):
			chat.supabase_config()

	def test_rpc_always_uses_configured_admin_even_if_overridden_in_params(self):
		with patch.object(chat, "request", return_value={}) as request:
			chat.rpc(chat.SEND_RPC, p_user="spoofed", p_sender_display_name="Alice")
			self.assertEqual(request.call_args.args[1]["p_user"], ADMIN)

	def test_two_staff_share_supabase_identity_but_send_different_server_names(self):
		payloads = []

		def remote(method, url, **kwargs):
			payload = kwargs["json"]
			payloads.append(payload)
			self.assertTrue(url.endswith("/rpc/api_frappe_admin_chat_send_message"))
			response = MagicMock(ok=True)
			response.json.return_value = {
				"id": MESSAGE,
				"sender_user_id": payload["p_user"],
				"sender_display_name": payload["p_sender_display_name"],
				"kind": "text",
			}
			return response

		with (
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "publish"),
			patch.object(chat.requests, "request", side_effect=remote),
		):
			for user, name in [("alice@example.com", " Alice Staff "), ("bob@example.com", "Bob Staff")]:
				frappe.session.user = user
				self.db.get_value.return_value = name
				saved = chat.save_message(CONVERSATION, CLIENT, "text", body="Hello")
				self.assertEqual(saved["sender_display_name"], name.strip())
				self.assertEqual(saved["sender_user_id"], ADMIN)
		self.assertEqual({p["p_user"] for p in payloads}, {ADMIN})
		self.assertEqual([p["p_sender_display_name"] for p in payloads], ["Alice Staff", "Bob Staff"])

	def test_new_send_failure_never_falls_back_to_shared_send(self):
		self.db.get_value.return_value = "Alice"
		with (
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "rpc", side_effect=Failure("PGRST202")) as rpc,
		):
			with self.assertRaises(Failure):
				chat.save_message(CONVERSATION, CLIENT, "text", body="Hello")
			rpc.assert_called_once()
			self.assertEqual(rpc.call_args.args[0], "api_frappe_admin_chat_send_message")

	def test_postgrest_errors_are_logged_fully_redacted_and_not_exposed(self):
		response = MagicMock(ok=False, status_code=404)
		response.json.return_value = {
			"code": "PGRST202",
			"message": "Mismatch sb_secret_hidden",
			"details": "Full details",
			"hint": "Inspect schema cache",
			"Authorization": "Bearer sb_secret_hidden",
		}
		with patch.object(chat.requests, "request", return_value=response):
			with self.assertRaisesRegex(Failure, "schema cache") as error:
				chat.rpc(chat.SEND_RPC, p_body="PRIVATE MESSAGE")
		logged = self.logger.error.call_args.args[0]
		self.assertIn("PGRST202", logged)
		self.assertIn("Full details", logged)
		self.assertIn("Inspect schema cache", logged)
		self.assertNotIn("sb_secret_hidden", logged)
		self.assertNotIn("PRIVATE MESSAGE", logged)
		self.assertNotIn("Full details", str(error.exception))

	def test_history_retains_canonical_alias_through_initial_and_older_pages(self):
		for cursor in [None, {"id": MESSAGE, "created_at": "2026-10-23T10:00:00Z"}]:
			result = {"items": [{"id": MESSAGE, "kind": "text", "sender_display_name": "Saved Alice"}]}
			with (
				patch.object(chat, "authorize"),
				patch.object(chat, "rpc", return_value=result) as rpc,
				patch.object(chat, "request") as lookup,
			):
				self.assertEqual(
					raw(chat.messages)(CONVERSATION, cursor)["items"][0]["sender_display_name"], "Saved Alice"
				)
				lookup.assert_not_called()
				self.assertEqual(rpc.call_args.kwargs["p_before_id"], MESSAGE if cursor else None)

	def test_history_enriches_alias_and_replaces_portal_photo_url(self):
		result = {"items": [{"id": MESSAGE, "kind": "photo", "media_url": "/chats/media/other"}]}
		with (
			patch.object(chat, "authorize"),
			patch.object(chat, "capabilities", return_value={"aliases": True}),
			patch.object(chat, "rpc", return_value=result),
			patch.object(
				chat, "request", return_value=[{"id": MESSAGE, "sender_display_name": "Saved Staff"}]
			),
		):
			item = raw(chat.messages)(CONVERSATION)["items"][0]
		self.assertEqual(item["sender_display_name"], "Saved Staff")
		self.assertTrue(item["media_url"].startswith("/api/method/"))
		self.assertNotIn("media_object_key", item)

	def test_media_authorization_precedes_r2_access(self):
		with (
			patch.object(chat, "authorize"),
			patch.object(chat, "rpc", side_effect=Failure("denied")),
			patch.object(chat.r2_client, "get_client") as client,
		):
			with self.assertRaises(Failure):
				raw(chat.media)(MESSAGE)
			client.assert_not_called()

	def test_media_private_response_and_existing_customer_object(self):
		key = f"chat/{CONVERSATION}/{CLIENT}-{'a' * 24}.png"
		client = MagicMock()
		client.get_object.return_value = {"Body": io.BytesIO(b"photo")}
		with (
			patch.object(chat, "authorize"),
			patch.object(chat, "rpc", return_value={"object_key": key, "content_type": "image/png"}),
			patch.object(chat, "photo_config"),
			patch.object(chat.r2_client, "get_client", return_value=client),
		):
			response = raw(chat.media)(MESSAGE)
		self.assertEqual(response.headers["Cache-Control"], "private, no-store")
		self.assertEqual(response.data, b"photo")
		self.assertEqual(client.get_object.call_args.kwargs["Bucket"], chat.BUCKET)

	def test_photo_bytes_are_validated_not_filename_or_claimed_mime(self):
		stream = io.BytesIO()
		Image.new("RGB", (2, 2)).save(stream, format="PNG")
		self.assertEqual(chat.validate_photo(stream.getvalue()), ("image/png", "png"))
		for data in [b"fake image", b"", b"a" * (chat.MAX_PHOTO + 1)]:
			with self.assertRaises(Failure):
				chat.validate_photo(data)

	def test_text_and_photo_endpoints_call_only_new_rpc_with_saved_staff_name(self):
		stream = io.BytesIO()
		Image.new("RGB", (2, 2)).save(stream, format="PNG")
		content = stream.getvalue()
		self.db.get_value.return_value = "  Current Staff  "
		client = MagicMock()

		def remote(name, **params):
			if name == "api_admin_chat_messages":
				return {}
			self.assertEqual(name, "api_frappe_admin_chat_send_message")
			return {"id": MESSAGE, "kind": params["p_kind"], "sender_display_name": "Original Saved Staff"}

		with (
			patch.object(chat, "authorize"),
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "rpc", side_effect=remote) as rpc,
			patch.object(chat, "publish"),
			patch.object(chat, "photo_config"),
			patch.object(chat.r2_client, "ownership", return_value={}),
			patch.object(chat.r2_client, "get_client", return_value=client),
			patch.object(
				frappe,
				"request",
				SimpleNamespace(files={"file": SimpleNamespace(stream=io.BytesIO(content))}),
			),
		):
			text = raw(chat.send_text)(CONVERSATION, CLIENT, "Hello")
			photo = raw(chat.send_photo)(CONVERSATION, CLIENT)
			self.assertEqual(text["sender_display_name"], "Original Saved Staff")
			self.assertEqual(photo["sender_display_name"], "Original Saved Staff")
			self.assertTrue(photo["media_url"].startswith("/api/method/"))
			sends = [
				call for call in rpc.call_args_list if call.args[0] == "api_frappe_admin_chat_send_message"
			]
			self.assertEqual(len(sends), 2)
			for call in sends:
				self.assertEqual(call.kwargs["p_sender_display_name"], "Current Staff")
				self.assertEqual(call.kwargs["p_client_message"], CLIENT)
			self.assertEqual(sends[0].kwargs["p_kind"], "text")
			self.assertIsNone(sends[0].kwargs["p_media_key"])
			self.assertEqual(sends[1].kwargs["p_kind"], "photo")
			self.assertIsNone(sends[1].kwargs["p_body"])
			self.assertEqual(sends[1].kwargs["p_media_type"], "image/png")
			self.assertEqual(sends[1].kwargs["p_media_size"], len(content))
			self.assertEqual(client.put_object.call_args.kwargs["Bucket"], "homeall-chat-staging")

	def test_invalid_staff_name_is_rejected_before_photo_upload(self):
		self.db.get_value.return_value = "a" * 256
		with (
			patch.object(chat, "authorize"),
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "rpc"),
			patch.object(chat.r2_client, "get_client") as client,
		):
			with self.assertRaisesRegex(Failure, "display name"):
				raw(chat.send_photo)(CONVERSATION, CLIENT)
			client.assert_not_called()

	def test_supabase_viewer_cannot_upload_a_photo_before_send_is_rejected(self):
		with (
			patch.object(chat, "require_staff"),
			patch.object(chat, "admin_role", return_value={"viewer"}),
			patch.object(chat, "rpc") as rpc,
			patch.object(chat.r2_client, "get_client") as client,
		):
			with self.assertRaisesRegex(Failure, "read-only"):
				raw(chat.send_photo)(CONVERSATION, CLIENT)
			rpc.assert_not_called()
			client.assert_not_called()

	def test_unauthorized_sends_cannot_call_rpc_or_upload(self):
		with (
			patch.object(chat, "authorize", side_effect=Failure("denied")),
			patch.object(chat, "rpc") as rpc,
			patch.object(chat.r2_client, "get_client") as client,
		):
			with self.assertRaises(Failure):
				raw(chat.send_text)(CONVERSATION, CLIENT, "Hello")
			with self.assertRaises(Failure):
				raw(chat.send_photo)(CONVERSATION, CLIENT)
			rpc.assert_not_called()
			client.assert_not_called()

	def test_photo_retry_uses_identical_original_fingerprint_and_never_deletes(self):
		stream = io.BytesIO()
		Image.new("RGB", (2, 2)).save(stream, format="PNG")
		content = stream.getvalue()
		client = MagicMock()
		with (
			patch.object(chat, "authorize"),
			patch.object(chat, "rpc"),
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "photo_config"),
			patch.object(chat.r2_client, "ownership", return_value={}),
			patch.object(chat.r2_client, "get_client", return_value=client),
			patch.object(chat, "save_message", side_effect=Failure("uncertain")) as save,
		):
			for _ in range(2):
				with patch.object(
					frappe,
					"request",
					SimpleNamespace(files={"file": SimpleNamespace(stream=io.BytesIO(content))}),
				):
					with self.assertRaises(Failure):
						raw(chat.send_photo)(CONVERSATION, CLIENT)
			self.assertEqual(
				save.call_args.kwargs["media_key"],
				f"chat/{CONVERSATION}/{CLIENT}-{hashlib.sha256(content).hexdigest()[:24]}.png",
			)
			self.assertEqual(client.put_object.call_args_list[0], client.put_object.call_args_list[1])
			client.delete_object.assert_not_called()

	def test_read_state_is_published_to_other_staff(self):
		with (
			patch.object(chat, "authorize"),
			patch.object(chat, "rpc", return_value={}) as rpc,
			patch.object(chat, "publish") as publish,
		):
			raw(chat.mark_read)(CONVERSATION, MESSAGE)
			self.assertEqual(rpc.call_args.kwargs["p_message"], MESSAGE)
			publish.assert_called_once_with(
				{"event": "read_updated", "conversation_id": CONVERSATION, "message_id": MESSAGE}
			)

	def test_realtime_publish_is_explicitly_user_scoped(self):
		with (
			patch.object(chat, "recipients", return_value=["allowed@example.com"]),
			patch.object(frappe, "publish_realtime") as publish,
		):
			chat.publish({"event": "read_updated"})
			self.assertEqual(publish.call_args.kwargs["user"], "allowed@example.com")

	def test_bridge_normalizes_v2_and_legacy_without_forwarding_content(self):
		for event in [
			{
				"payload": {
					"message": {
						"id": MESSAGE,
						"conversation_id": CONVERSATION,
						"body": "private",
						"sender_display_name": "Staff",
					}
				}
			},
			{"conversation_id": CONVERSATION, "message_id": MESSAGE},
		]:
			self.assertEqual(
				bridge.identifiers("message_created", event),
				{"event": "message_created", "conversation_id": CONVERSATION, "message_id": MESSAGE},
			)
		self.assertIsNone(bridge.identifiers("context_updated", {"conversation_id": "invalid"}))

	def test_bridge_deduplicates_events_before_delivery(self):
		cache = MagicMock()
		cache.set.return_value = False
		with (
			patch.object(bridge, "fresh_site"),
			patch.object(frappe, "cache", return_value=cache),
			patch.object(chat, "recipients") as recipients,
		):
			bridge.deliver("message_created", {"conversation_id": CONVERSATION, "message_id": MESSAGE})
			recipients.assert_not_called()

	def test_bridge_forwards_ids_without_remote_or_notification_work_on_live_path(self):
		cache = MagicMock()
		cache.set.return_value = True
		with (
			patch.object(bridge, "fresh_site"),
			patch.object(frappe, "cache", return_value=cache),
			patch.object(chat, "admin_role", side_effect=AssertionError("Blocking remote role lookup")),
			patch.object(chat, "request", side_effect=AssertionError("Blocking stored-message lookup")),
			patch.object(chat, "recipients", return_value=["allowed@example.com"]),
			patch.object(frappe, "publish_realtime") as publish,
			patch.object(frappe, "enqueue") as enqueue,
		):
			bridge.deliver("message_created", {"conversation_id": CONVERSATION, "message_id": MESSAGE})
			publish.assert_called_once_with(
				chat.EVENT,
				{"event": "message_created", "conversation_id": CONVERSATION, "message_id": MESSAGE},
				user="allowed@example.com",
				after_commit=False,
			)
			self.assertEqual(enqueue.call_args.kwargs["message_id"], MESSAGE)
			self.assertTrue(enqueue.call_args.kwargs["deduplicate"])

	def test_customer_event_enqueues_deduplicated_frappe_bell_notification(self):
		with (
			patch.object(chat, "admin_role"),
			patch.object(chat, "recipients", return_value=["allowed@example.com"]),
			patch.object(chat, "request", return_value=[{"sender_role": "customer"}]),
			patch(
				"frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification"
			) as notify,
		):
			bridge.notify_customer_message(CONVERSATION, MESSAGE)
			self.assertEqual(notify.call_args.args[0], ["allowed@example.com"])
			self.assertIn(MESSAGE, notify.call_args.args[1]["link"])
			self.assertEqual(notify.call_args.kwargs["dedupe_on"], ["link"])

	def test_notification_worker_rechecks_membership_and_suppresses_admin_echoes(self):
		with (
			patch.object(chat, "admin_role", side_effect=Failure("Membership revoked")),
			patch.object(chat, "request") as request,
		):
			with self.assertRaises(Failure):
				bridge.notify_customer_message(CONVERSATION, MESSAGE)
			request.assert_not_called()
		with (
			patch.object(chat, "admin_role"),
			patch.object(chat, "request", return_value=[{"sender_role": "admin"}]),
			patch.object(chat, "recipients") as recipients,
		):
			bridge.notify_customer_message(CONVERSATION, MESSAGE)
			recipients.assert_not_called()

	def test_notification_queue_failure_does_not_reconnect_or_undo_live_delivery(self):
		cache = MagicMock()
		cache.set.return_value = True
		with (
			patch.object(bridge, "fresh_site"),
			patch.object(frappe, "cache", return_value=cache),
			patch.object(chat, "recipients", return_value=["allowed@example.com"]),
			patch.object(frappe, "publish_realtime") as publish,
			patch.object(frappe, "enqueue", side_effect=RuntimeError("Queue unavailable")),
		):
			bridge.deliver("message_created", {"conversation_id": CONVERSATION, "message_id": MESSAGE})
			publish.assert_called_once()
			cache.delete.assert_not_called()
			self.logger.error.assert_called_once()

	def test_lost_bridge_lease_prevents_delivery_and_releases_dedup_claim(self):
		cache = MagicMock()
		cache.set.return_value = True
		with (
			patch.object(bridge, "fresh_site"),
			patch.object(frappe, "cache", return_value=cache),
			patch.object(chat, "admin_role"),
			patch.object(chat, "recipients", return_value=["allowed@example.com"]),
			patch.object(chat, "request", return_value=[{"sender_role": "customer"}]),
			patch.object(frappe, "publish_realtime") as publish,
		):
			with self.assertRaises(Failure):
				bridge.deliver(
					"message_created",
					{"conversation_id": CONVERSATION, "message_id": MESSAGE},
					ensure_lease=MagicMock(side_effect=Failure("lease lost")),
				)
			publish.assert_not_called()
			cache.delete.assert_called_once()

	def test_inbox_and_history_do_not_precede_rpc_with_profile_requests(self):
		response = MagicMock(ok=True)
		response.json.return_value = {"items": []}
		with (
			patch.object(chat, "require_staff") as permission,
			patch.object(chat, "admin_role") as roles,
			patch.object(chat.requests, "request", return_value=response) as request,
		):
			raw(chat.conversations)()
			self.assertEqual(request.call_count, 1)
			self.assertTrue(request.call_args.args[1].endswith("/rpc/api_admin_chat_conversations"))
			request.reset_mock()
			raw(chat.messages)(CONVERSATION)
			self.assertEqual(request.call_count, 1)
			self.assertTrue(request.call_args.args[1].endswith("/rpc/api_admin_chat_messages"))
			self.assertEqual(permission.call_count, 2)
			roles.assert_not_called()

	def test_bootstrap_checks_admin_once_and_can_bundle_initial_inbox(self):
		page = {"items": [], "has_more": False}
		with (
			patch.object(chat, "require_staff"),
			patch.object(chat, "admin_role", return_value={"owner"}) as role,
			patch.object(chat, "allowed_user", return_value=True),
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "staff_name", return_value="Staff"),
			patch.object(chat, "bridge_health", return_value={}),
			patch.object(chat, "rpc", return_value=page) as rpc,
		):
			result = raw(chat.bootstrap)(include_inbox=True)
			self.assertEqual(result["inbox"], page)
			role.assert_called_once()
			rpc.assert_called_once()

	def test_text_send_needs_one_rpc_even_when_capability_cache_expired(self):
		self.db.get_value.return_value = "Staff"
		response = MagicMock(ok=True)
		response.json.return_value = {"id": MESSAGE, "kind": "text", "sender_display_name": "Staff"}
		with (
			patch.object(chat, "require_staff"),
			patch.object(chat, "publish"),
			patch.object(chat, "capabilities", side_effect=AssertionError("Unexpected schema request")),
			patch.object(chat.requests, "request", return_value=response) as request,
		):
			self.assertEqual(raw(chat.send_text)(CONVERSATION, CLIENT, "Hello")["id"], MESSAGE)
			request.assert_called_once()
			self.assertTrue(request.call_args.args[1].endswith("/rpc/api_frappe_admin_chat_send_message"))

	def test_committed_send_and_read_survive_local_realtime_failure(self):
		self.db.get_value.return_value = "Staff"
		saved = {"id": MESSAGE, "sender_display_name": "Saved Staff", "kind": "text"}
		with (
			patch.object(chat, "authorize"),
			patch.object(chat, "capabilities", return_value=READY),
			patch.object(chat, "rpc", return_value=saved),
			patch.object(chat, "publish", side_effect=RuntimeError("Redis offline")),
		):
			self.assertEqual(
				raw(chat.send_text)(CONVERSATION, CLIENT, "Hello")["sender_display_name"], "Saved Staff"
			)
			self.assertEqual(raw(chat.mark_read)(CONVERSATION, MESSAGE), saved)
			self.assertEqual(self.logger.error.call_count, 2)

	def test_send_returns_saved_message_before_notifying_other_staff(self):
		callbacks = []
		request = SimpleNamespace(after_response=SimpleNamespace(add=callbacks.append))
		saved = {"id": MESSAGE, "sender_display_name": "Saved Staff", "kind": "text"}
		with (
			patch.object(frappe, "local", SimpleNamespace(request=request)),
			patch.object(chat, "authorize"),
			patch.object(chat, "staff_name", return_value="Saved Staff"),
			patch.object(chat, "rpc", return_value=saved),
			patch.object(chat, "publish") as publish,
		):
			self.assertEqual(raw(chat.send_text)(CONVERSATION, CLIENT, "Hello")["id"], MESSAGE)
			publish.assert_not_called()
			self.assertEqual(len(callbacks), 1)
			callbacks[0]()
			publish.assert_called_once_with(
				{"event": "message_created", "conversation_id": CONVERSATION, "message_id": MESSAGE}
			)

	def test_send_timing_headers_contain_durations_without_message_content(self):
		headers = Headers()
		with (
			patch.object(frappe, "local", SimpleNamespace(response_headers=headers)),
			patch.object(chat, "authorize"),
			patch.object(chat, "save_message", return_value={"id": MESSAGE}),
		):
			raw(chat.send_text)(CONVERSATION, CLIENT, "Private text")
		self.assertEqual(len(headers.getlist("Server-Timing")), 2)
		for value in headers.getlist("Server-Timing"):
			self.assertRegex(value, r"^chat_(auth|send);dur=\d+\.\d$")
			self.assertNotIn("Private text", value)

	def test_bridge_site_job_always_destroys_its_worker_context(self):
		with (
			patch.object(frappe, "init") as init,
			patch.object(frappe, "connect"),
			patch.object(frappe, "destroy") as destroy,
		):
			with self.assertRaises(Failure):
				bridge.site_job("example.test", ".", MagicMock(side_effect=Failure("offline")))
			init.assert_called_once_with(site="example.test", sites_path=".", force=True)
			destroy.assert_called_once()


class BridgeLifecycleTests(unittest.IsolatedAsyncioTestCase):
	async def test_duplicate_instance_is_refused_using_site_scoped_lock(self):
		cache = MagicMock()
		cache.make_key.return_value = b"site-db|homeall_chat:bridge"
		cache.lock.return_value.acquire.return_value = False
		with patch.object(frappe, "cache", return_value=cache):
			with self.assertRaisesRegex(RuntimeError, "already running"):
				await bridge.consume(asyncio.Event())
		self.assertEqual(cache.lock.call_args.args[0], b"site-db|homeall_chat:bridge")

	async def test_graceful_shutdown_releases_owned_lease(self):
		cache = MagicMock()
		cache.lock.return_value.owned.return_value = True
		stop = asyncio.Event()
		stop.set()

		async def direct_call(callback, *args):
			return callback(*args)

		with (
			patch.object(frappe, "cache", return_value=cache),
			patch.object(chat, "admin_role"),
			patch.object(bridge, "site_call", side_effect=direct_call),
			patch.object(bridge, "health") as health,
		):
			await bridge.consume(stop)
		cache.lock.return_value.release.assert_called_once()
		health.assert_called_once_with("Offline")

	async def test_slow_bridge_work_does_not_block_websocket_event_loop(self):
		def blocking_job(*args):
			time.sleep(0.08)
			return "done"

		with (
			patch.object(frappe, "local", SimpleNamespace(site="example.test", sites_path=".")),
			patch.object(bridge, "site_job", side_effect=blocking_job),
		):
			job = asyncio.create_task(bridge.site_call(lambda: None))
			await asyncio.sleep(0.01)
			self.assertFalse(job.done(), "Blocking delivery prevented the event loop from running")
			self.assertEqual(await job, "done")


class HttpSessionTests(unittest.TestCase):
	def test_ipv4_resolution_restores_hostname_before_tls_and_http(self):
		connection = chat.ChatHTTPSConnection("project.supabase.co", 443)
		marker = object()
		addresses = [(chat.socket.AF_INET, chat.socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))]

		def connect(conn):
			self.assertEqual(conn.host, "192.0.2.1")
			return marker

		with (
			patch.object(chat.socket, "getaddrinfo", return_value=addresses) as lookup,
			patch.object(chat.HTTPSConnection, "_new_conn", connect),
		):
			self.assertIs(connection._new_conn(), marker)
			lookup.assert_called_once_with(
				"project.supabase.co", 443, chat.socket.AF_INET, chat.socket.SOCK_STREAM
			)
		self.assertEqual(connection.host, "project.supabase.co")

	def test_connection_fallback_tries_other_addresses_before_any_http_request(self):
		connection = chat.ChatHTTPSConnection("project.supabase.co", 443)
		addresses = [
			(chat.socket.AF_INET, chat.socket.SOCK_STREAM, 6, "", (address, 443))
			for address in ("192.0.2.1", "192.0.2.2")
		]
		attempted = []

		def connect(conn):
			attempted.append(conn.host)
			if conn.host == "192.0.2.1":
				raise chat.ConnectTimeoutError("First address unavailable")
			return "socket"

		with (
			patch.object(chat.socket, "getaddrinfo", return_value=addresses),
			patch.object(chat.HTTPSConnection, "_new_conn", connect),
		):
			self.assertEqual(connection._new_conn(), "socket")
		self.assertEqual(attempted, ["192.0.2.1", "192.0.2.2"])
		self.assertEqual(connection.host, "project.supabase.co")

	def test_ipv6_only_hosts_retain_standard_connection_behavior(self):
		connection = chat.ChatHTTPSConnection("ipv6.example.test", 443)
		with (
			patch.object(chat.socket, "getaddrinfo", side_effect=chat.socket.gaierror("No A record")),
			patch.object(chat.HTTPSConnection, "_new_conn", return_value="ipv6-socket"),
		):
			self.assertEqual(connection._new_conn(), "ipv6-socket")
		self.assertEqual(connection.host, "ipv6.example.test")

	def test_dns_override_is_scoped_to_chat_adapter(self):
		standard = chat.requests.adapters.HTTPAdapter()
		adapter = chat.ChatHTTPAdapter()
		self.assertIsNot(standard.poolmanager.pool_classes_by_scheme["https"], chat.ChatHTTPSConnectionPool)
		self.assertIs(adapter.poolmanager.pool_classes_by_scheme["https"], chat.ChatHTTPSConnectionPool)
		self.assertIs(
			adapter.proxy_manager_for("http://proxy.example.test").pool_classes_by_scheme["https"],
			chat.ChatHTTPSConnectionPool,
		)
		standard.close()
		adapter.close()

	def test_new_request_threads_share_connections_without_sharing_session_state(self):
		sessions = []
		adapter = chat.requests.adapters.HTTPAdapter(max_retries=0)
		with (
			patch.object(chat, "_http", threading.local()),
			patch.object(chat, "http_adapter", return_value=adapter),
		):
			for _ in range(2):
				worker = threading.Thread(target=lambda: sessions.append(chat.http_session()))
				worker.start()
				worker.join()
		self.assertEqual(len(sessions), 2)
		self.assertIsNot(sessions[0], sessions[1])
		self.assertIs(sessions[0].get_adapter("https://test.supabase.co"), adapter)
		self.assertIs(sessions[1].get_adapter("https://test.supabase.co"), adapter)
		sessions[0].headers["Authorization"] = "test-only-token"
		sessions[0].cookies.set("test", "first-session")
		self.assertNotIn("Authorization", sessions[1].headers)
		self.assertNotIn("test", sessions[1].cookies)
		for session in sessions:
			session.close()

	def test_forked_process_uses_a_separate_connection_pool(self):
		chat.http_adapter.cache_clear()
		first, second = MagicMock(), MagicMock()
		with patch.object(chat, "ChatHTTPAdapter", side_effect=[first, second]) as factory:
			self.assertIs(chat.http_adapter(10), first)
			self.assertIs(chat.http_adapter(10), first)
			self.assertIs(chat.http_adapter(11), second)
			self.assertEqual(factory.call_count, 2)
		chat.http_adapter.cache_clear()

	def test_connections_are_reused_and_replaced_after_a_worker_fork(self):
		first, second = MagicMock(), MagicMock()
		with (
			patch.object(chat, "_http", SimpleNamespace()),
			patch.object(chat.requests, "Session", side_effect=[first, second]) as factory,
			patch.object(chat.os, "getpid", return_value=10) as pid,
		):
			self.assertIs(chat.http_session(), first)
			self.assertIs(chat.http_session(), first)
			self.assertEqual(factory.call_count, 1)
			pid.return_value = 11
			self.assertIs(chat.http_session(), second)
			first.close.assert_called_once()
			self.assertEqual(factory.call_count, 2)


if __name__ == "__main__":
	unittest.main()
