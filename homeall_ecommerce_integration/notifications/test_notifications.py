"""Offline security and failure-recovery checks; no messages are sent."""

import hashlib
import hmac
import json
import time
import unittest
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import frappe
from werkzeug.exceptions import HTTPException
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from . import api, policy, worker

ID = "10000000-0000-4000-8000-000000000001"
ORDER = "20000000-0000-4000-8000-000000000002"


class PolicyTests(unittest.TestCase):
	def test_signature_is_bound_to_timestamp_and_exact_bytes(self):
		body = b'{"id":"x"}'
		signature = hmac.new(b"secret", b"1000." + body, hashlib.sha256).hexdigest()
		self.assertTrue(policy.verify_signature("secret", "1000", signature, body, now=1000))
		for secret, stamp, value, payload, now in [
			("wrong", "1000", signature, body, 1000),
			("secret", "1000", signature, body + b" ", 1000),
			("secret", "1000", signature, body, 1301),
			("secret", "1000", signature, body, 699),
			("secret", "invalid", signature, body, 1000),
			("", "1000", signature, body, 1000),
		]:
			self.assertFalse(policy.verify_signature(secret, stamp, value, payload, now=now))

	def test_event_discards_remote_html_and_destinations(self):
		result = policy.normalize_event(
			{
				"id": ID,
				"type": "order_created",
				"created_at": "2026-01-01T00:00:00Z",
				"payload": {"order_id": ORDER, "customer_name": "private"},
				"title": "<script>",
				"destination": "https://evil.test",
			}
		)
		self.assertEqual(result["title"], "New online order")
		self.assertEqual(result["payload"], {"order_id": ORDER})
		self.assertEqual(result["destination"], "/desk/online-order?order=" + ORDER)

	def test_rejects_wrong_types_invalid_identifiers_and_naive_dates(self):
		base = {
			"id": ID,
			"type": "order_created",
			"created_at": "2026-01-01T00:00:00Z",
			"payload": {"order_id": ORDER},
		}
		for change in [
			{"type": "order_payment"},
			{"id": "../evil"},
			{"payload": {}},
			{"created_at": "2026-01-01"},
		]:
			with self.assertRaises((ValueError, KeyError)):
				policy.normalize_event(base | change)

	def test_delivery_identity_separates_users_and_devices_and_ttl_expires(self):
		self.assertNotEqual(policy.delivery_key(ID, "alice"), policy.delivery_key(ID, "bob"))
		self.assertNotEqual(
			policy.delivery_key(ID, "alice", "phone"), policy.delivery_key(ID, "alice", "desktop")
		)
		self.assertTrue(policy.expired("1970-01-01T00:00:00+00:00", 3600, now=3601))


class WorkerTests(unittest.TestCase):
	def setUp(self):
		self.db = MagicMock()
		self.cfg = {"enabled": 1, "push_enabled": 1}
		self.row = frappe._dict(
			name="delivery",
			parent=ID,
			user="alice",
			subscription="device",
			generation="v1",
			status="Pending",
			attempts=0,
			next_attempt_at=datetime(2020, 1, 1),
			claimed_at=None,
		)
		self.event = frappe._dict(name=ID, occurred_at=datetime.now(UTC).isoformat())
		self.device = frappe._dict(name="device", user="alice", enabled=1, generation="v1")
		for obj, attr, value in [
			(frappe, "db", self.db),
			(worker, "settings", lambda: self.cfg),
			(worker, "now_datetime", datetime.now),
			(worker, "eligible", lambda user: True),
		]:
			p = patch.object(obj, attr, value)
			p.start()
			self.addCleanup(p.stop)
		p = patch.object(
			frappe,
			"get_doc",
			side_effect=lambda kind, name, **kwargs: {
				worker.DELIVERY: self.row,
				worker.EVENT: self.event,
				worker.SUBSCRIPTION: self.device,
			}[kind],
		)
		p.start()
		self.addCleanup(p.stop)
		self.db.get_value.side_effect = lambda *a, **k: frappe._dict(
			status="Sending", attempts=self.row.attempts + 1
		)

	def test_commit_claim_before_network_then_record_success(self):
		def network(*args):
			self.db.commit.assert_called_once()

		with patch.object(worker, "send_push", side_effect=network):
			worker.send_delivery("delivery")
		self.assertEqual(self.db.set_value.call_args.args[2]["status"], "Sent")

	def test_failure_retries_only_this_delivery_and_sanitizes_exception(self):
		with patch.object(worker, "send_push", side_effect=RuntimeError("SECRET_TOKEN")):
			worker.send_delivery("delivery")
		result = self.db.set_value.call_args.args[2]
		self.assertEqual(result["status"], "Pending")
		self.assertEqual(result["last_error"], "RuntimeError")
		self.assertNotIn("SECRET_TOKEN", str(self.db.mock_calls))

	def test_account_switch_or_token_rotation_skips_old_delivery(self):
		for change in [{"user": "bob"}, {"generation": "v2"}, {"enabled": 0}]:
			self.device.update(user="alice", enabled=1, generation="v1")
			self.device.update(change)
			with patch.object(worker, "send_push") as send:
				worker.send_delivery("delivery")
				send.assert_not_called()
			self.assertEqual(self.db.set_value.call_args.args[3], "Skipped")

	def test_final_crashed_lease_becomes_failed(self):
		self.row.update(status="Sending", attempts=8, claimed_at=datetime(2020, 1, 1))
		with patch.object(worker, "send_push") as send:
			worker.send_delivery("delivery")
			send.assert_not_called()
		self.assertEqual(self.db.set_value.call_args.args[2]["status"], "Failed")

	def test_active_lease_and_success_are_never_sent_again(self):
		for state in ["Sent", "Failed", "Skipped", "Sending"]:
			self.row.update(status=state, claimed_at=datetime.now())
			with patch.object(worker, "send_push") as send:
				worker.send_delivery("delivery")
				send.assert_not_called()

	def test_eighth_failed_send_is_exhausted(self):
		self.row.attempts = 7
		with patch.object(worker, "send_push", side_effect=RuntimeError("offline")):
			worker.send_delivery("delivery")
		self.assertEqual(self.db.set_value.call_args.args[2]["status"], "Failed")

	def test_permanent_token_failure_disables_only_matching_generation(self):
		error = type("UnregisteredError", (Exception,), {})
		with patch.object(worker, "send_push", side_effect=error()):
			worker.send_delivery("delivery")
		self.db.set_value.assert_any_call(
			worker.SUBSCRIPTION, {"name": "device", "generation": "v1"}, "enabled", 0
		)
		self.assertEqual(self.db.set_value.call_args.args[2]["status"], "Skipped")

	def test_real_firebase_sdk_accepts_generic_data_only_web_push(self):
		import firebase_admin
		from firebase_admin import _messaging_encoder, messaging

		self.cfg["firebase_service_account"] = {"project_id": "test-project"}
		device = MagicMock()
		device.get_password.return_value = "registration-token"
		self.event.update(
			event_type="order_created",
			title="New online order",
			destination="/desk/online-order?order=" + ORDER,
		)
		with (
			patch.object(frappe.local, "site", "test-site", create=True),
			patch.object(firebase_admin, "get_app", return_value=MagicMock()),
			patch.object(messaging, "send", return_value="message-id") as send,
		):
			worker.send_push(device, self.event, 3600)
			encoded = json.loads(_messaging_encoder.MessageEncoder().encode(send.call_args.args[0]))
			self.assertNotIn("notification", encoded)
			self.assertEqual(encoded["webpush"]["headers"]["TTL"], "3600")
			self.assertEqual(encoded["data"]["title"], "New online order")
			self.assertIn("homeall_event=" + ID, encoded["data"]["destination"])


class ApiTests(unittest.TestCase):
	def test_guest_login_preserves_only_validated_same_origin_destination(self):
		request = Request(
			EnvironBuilder(
				path="/desk/online-order",
				query_string={
					"order": ORDER,
					"homeall_event": ID,
					"redirect": "https://evil.test",
				},
			).get_environ()
		)
		with (
			patch.object(frappe, "request", request),
			patch.object(frappe, "session", frappe._dict(user="Guest")),
		):
			with self.assertRaises(HTTPException) as caught:
				api.preserve_notification_login()
		response = caught.exception.get_response()
		self.assertEqual(response.status_code, 302)
		target = parse_qs(urlsplit(response.headers["Location"]).query)["redirect-to"][0]
		self.assertEqual(target, f"/desk/online-order?order={ORDER}&homeall_event={ID}")
		self.assertEqual(response.headers["Cache-Control"], "no-store")

	def test_unrelated_routes_and_invalid_ids_are_not_redirected_by_hook(self):
		for path, query in [
			("/desk/user", {"order": ORDER}),
			("/desk/online-order", {"order": "https://evil.test"}),
		]:
			request = Request(EnvironBuilder(path=path, query_string=query).get_environ())
			with (
				patch.object(frappe, "request", request),
				patch.object(frappe, "session", frappe._dict(user="Guest")),
			):
				api.preserve_notification_login()

	def test_registration_refresh_preserves_binding_but_account_switch_rotates_it(self):
		token = "firebase-token-1234567890"
		doc = frappe._dict(
			user="alice",
			enabled=1,
			token_hash=hashlib.sha256(token.encode()).hexdigest(),
			generation="binding-v1",
		)
		doc.save = MagicMock()
		with (
			patch.object(api, "require_staff"),
			patch.object(api, "settings", return_value={"enabled": 1, "push_enabled": 1}),
			patch.object(api, "now_datetime", datetime.now),
			patch.object(frappe, "cache", MagicMock()),
			patch.object(frappe, "db", MagicMock()),
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "session", frappe._dict(user="alice", sid="alice-session")),
		):
			api.register.__wrapped__(ID, token)
			self.assertEqual(doc.generation, "binding-v1")
			with patch.object(frappe, "session", frappe._dict(user="bob", sid="bob-session")):
				api.register.__wrapped__(ID, token)
			self.assertEqual(doc.user, "bob")
			self.assertNotEqual(doc.generation, "binding-v1")

	def test_refresh_keeps_loaded_timestamp_and_disables_other_token_registrations(self):
		token = "firebase-token-1234567890"
		fingerprint = hashlib.sha256(token.encode()).hexdigest()
		other_id = "30000000-0000-4000-8000-000000000003"
		rows = {
			name: frappe._dict(
				name=name,
				user="alice",
				token_hash=fingerprint,
				enabled=1,
				generation="binding-v1",
				modified=datetime(2026, 1, 1),
			)
			for name in (ID, other_id)
		}
		doc = frappe._dict(rows[ID])

		def update_matching(doctype, filters, field, value):
			for row in rows.values():
				if row.token_hash != filters["token_hash"]:
					continue
				if "name" in filters and filters["name"] == ["!=", row.name]:
					continue
				row[field] = value
				row.modified += timedelta(microseconds=1)

		def save(**kwargs):
			# Model Frappe's check_if_latest: a bulk update must never stale the
			# document that the registration request already loaded for saving.
			self.assertEqual(rows[ID].modified, doc.modified)
			rows[ID].update({key: value for key, value in doc.items() if key != "save"})

		doc.save = MagicMock(side_effect=save)
		db = MagicMock()
		db.get_value.return_value = ID
		db.set_value.side_effect = update_matching
		with (
			patch.object(api, "require_staff"),
			patch.object(api, "settings", return_value={"enabled": 1, "push_enabled": 1}),
			patch.object(api, "now_datetime", datetime.now),
			patch.object(frappe, "cache", MagicMock()),
			patch.object(frappe, "db", db),
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "session", frappe._dict(user="alice", sid="session")),
		):
			self.assertEqual(api.register.__wrapped__(ID, token), {"enabled": True})
		self.assertEqual(rows[ID].enabled, 1)
		self.assertEqual(rows[ID].generation, "binding-v1")
		self.assertEqual(rows[other_id].enabled, 0)

	def test_public_configuration_never_contains_server_secrets(self):
		with patch.object(
			api,
			"settings",
			return_value={
				"firebase_web_config": {"apiKey": "public", "private_key": "secret"},
				"firebase_service_account": {"private_key": "secret"},
				"webhook_secret": "secret",
			},
		):
			self.assertEqual(api.public_config(), {"apiKey": "public"})

	def test_queue_failure_is_left_for_scheduler(self):
		with patch.object(frappe, "enqueue", side_effect=RuntimeError), patch.object(frappe, "logger"):
			api.enqueue_event(ID)

	def test_logout_disables_only_current_user_session(self):
		with (
			patch.object(frappe, "db", MagicMock()) as db,
			patch.object(frappe, "session", frappe._dict(user="alice", sid="session1")),
		):
			db.table_exists.return_value = True
			api.on_logout()
			filters = db.set_value.call_args.args[1]
			self.assertEqual(filters["user"], "alice")
			self.assertEqual(filters["session_hash"], hashlib.sha256(b"session1").hexdigest())

	def test_webhook_persists_before_queue_and_ignores_duplicate_insert(self):
		value = {
			"id": ID,
			"type": "order_created",
			"created_at": "2026-01-01T00:00:00Z",
			"payload": {"order_id": ORDER},
		}
		body = json.dumps(value).encode()
		stamp = str(int(time.time()))
		sig = hmac.new(b"secret", stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
		with (
			patch.object(api, "settings", return_value={"enabled": 1, "webhook_secret": "secret"}),
			patch.object(frappe, "db", MagicMock()) as db,
			patch.object(frappe, "request", MagicMock()) as request,
			patch.object(
				frappe,
				"get_request_header",
				side_effect=lambda key: stamp if key.endswith("Timestamp") else sig,
			),
		):
			request.get_data.return_value = body
			result = api.receive_event.__wrapped__()
			self.assertEqual(result, {"accepted": True, "event_id": ID})
			self.assertIn("insert ignore", db.sql.call_args.args[0])
			db.after_commit.add.assert_called_once()


class FanoutTests(unittest.TestCase):
	def test_bell_without_push_consent_and_duplicate_event_is_not_recreated(self):
		event = MagicMock()
		event.name = ID
		event.status = "Pending"
		event.destination = "/desk/online-order?order=" + ORDER
		event.title = "New online order"
		log = MagicMock()
		log.insert.return_value.name = "bell-entry"

		def document(kind, *args, **kwargs):
			return event if kind == worker.EVENT else log

		def records(kind, **kwargs):
			return ["alice"] if kind == "User" else []

		with (
			patch.object(worker, "settings", return_value={"enabled": 1, "push_enabled": 1}),
			patch.object(worker, "eligible", return_value=True),
			patch.object(frappe, "db", MagicMock()),
			patch.object(frappe, "get_doc", side_effect=document) as documents,
			patch.object(frappe, "get_all", side_effect=records),
		):
			worker.process_event(ID)
			worker.process_event(ID)
			log.insert.assert_called_once()
			event.append.assert_called_once()
			self.assertEqual(event.append.call_args.args[1]["channel"], "Bell")
			self.assertEqual(event.status, "Ready")
			documents.assert_any_call(worker.EVENT, ID, for_update=True)
