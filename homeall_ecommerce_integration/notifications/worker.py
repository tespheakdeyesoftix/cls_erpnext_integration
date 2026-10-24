"""Database-backed fanout and independently retryable, leased device deliveries."""

import hashlib
import json
from datetime import datetime, timedelta

import frappe
from frappe.desk.doctype.notification_settings.notification_settings import is_notifications_enabled
from frappe.utils import cint, now_datetime

from .api import enqueue_event, settings, staff
from .policy import delivery_key, expired

EVENT = "Homeall Notification Event"
DELIVERY = "Homeall Notification Delivery"
SUBSCRIPTION = "Homeall Push Subscription"


def eligible(user):
	return staff(user) and is_notifications_enabled(user)


def process_event(event_id):
	if not cint(settings().get("enabled")):
		return
	event = frappe.get_doc(EVENT, event_id, for_update=True)
	if event.status == "Pending":
		# The event lock and one transaction cover logs and delivery rows together.
		users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name")
		for user in users:
			if not eligible(user):
				continue
			link = event.destination + "&homeall_event=" + event.name
			log = frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": user,
					"type": "Alert",
					"app": "homeall_ecommerce_integration",
					"title": event.title,
					"description": "Open Homeall to view the details.",
					"link": link,
				}
			).insert(ignore_permissions=True)
			event.append(
				"deliveries",
				{
					"delivery_key": delivery_key(event.name, user),
					"user": user,
					"channel": "Bell",
					"notification_log": log.name,
					"status": "Sent",
					"attempts": 0,
				},
			)
			if not cint(settings().get("push_enabled")):
				continue
			for device in frappe.get_all(
				SUBSCRIPTION, filters={"user": user, "enabled": 1}, fields=["name", "generation"]
			):
				event.append(
					"deliveries",
					{
						"delivery_key": delivery_key(event.name, user, device.name),
						"user": user,
						"channel": "Push",
						"subscription": device.name,
						"generation": device.generation,
						"notification_log": log.name,
						"status": "Pending",
						"attempts": 0,
						"next_attempt_at": now_datetime(),
					},
				)
		event.status = "Ready"
		event.save(ignore_permissions=True)
	frappe.db.commit()
	for row in frappe.get_all(
		DELIVERY, filters={"parent": event_id, "channel": "Push", "status": "Pending"}, pluck="name"
	):
		enqueue_delivery(row)


def enqueue_delivery(name):
	try:
		frappe.enqueue(
			"homeall_ecommerce_integration.notifications.worker.send_delivery",
			delivery_id=name,
			queue="short",
		)
	except Exception:
		frappe.logger("homeall_notifications", allow_site=True).error(
			"Push queued for scheduler recovery: %s", name
		)


def claimable(row, now):
	if row.status == "Sending":
		return bool(row.claimed_at and row.claimed_at <= now - timedelta(minutes=5))
	return row.status == "Pending" and (not row.next_attempt_at or row.next_attempt_at <= now)


def send_delivery(delivery_id):
	cfg = settings()
	if not cint(cfg.get("enabled")) or not cint(cfg.get("push_enabled")):
		return
	row = frappe.get_doc(DELIVERY, delivery_id, for_update=True)
	if not claimable(row, now_datetime()):
		frappe.db.commit()
		return
	if row.attempts >= 8:
		frappe.db.set_value(DELIVERY, row.name, {"status": "Failed", "last_error": "LeaseExhausted"})
		frappe.db.commit()
		return
	event = frappe.get_doc(EVENT, row.parent)
	device = frappe.get_doc(SUBSCRIPTION, row.subscription, for_update=True)
	ttl = max(60, min(86400, cint(cfg.get("push_ttl_seconds", 3600))))
	if (
		not eligible(row.user)
		or not device.enabled
		or device.user != row.user
		or device.generation != row.generation
		or expired(event.occurred_at, ttl)
	):
		frappe.db.set_value(DELIVERY, row.name, "status", "Skipped")
		frappe.db.commit()
		return
	attempt = row.attempts + 1
	frappe.db.set_value(
		DELIVERY,
		row.name,
		{
			"status": "Sending",
			"attempts": attempt,
			"claimed_at": now_datetime(),
			"last_error": None,
		},
	)
	# Release the row lock before contacting Firebase. A crashed worker is recovered
	# by its five-minute lease; successful devices never get retried with a failed one.
	frappe.db.commit()
	status, error = "Sent", None
	try:
		send_push(device, event, ttl)
	except Exception as exc:
		# Never store exception text, which can contain credentials or registration tokens.
		error = type(exc).__name__[:100]
		if error in {"UnregisteredError", "SenderIdMismatchError"}:
			frappe.db.set_value(
				SUBSCRIPTION, {"name": device.name, "generation": row.generation}, "enabled", 0
			)
			status = "Skipped"
		else:
			status = "Failed" if attempt >= 8 else "Pending"
	# Guard against a late response from an older lease overwriting a newer attempt.
	current = frappe.db.get_value(
		DELIVERY, delivery_id, ["status", "attempts"], as_dict=True, for_update=True
	)
	if current and current.status == "Sending" and current.attempts == attempt:
		frappe.db.set_value(
			DELIVERY,
			delivery_id,
			{
				"status": status,
				"last_error": error,
				"claimed_at": None,
				"next_attempt_at": now_datetime() + timedelta(seconds=min(86400, 60 * 3 ** (attempt - 1))),
			},
		)
	frappe.db.commit()


def send_push(device, event, ttl):
	import firebase_admin
	from firebase_admin import credentials, messaging

	cfg = settings()
	credential = cfg.get("firebase_service_account")
	if not credential:
		raise RuntimeError("Firebase service account is not configured")
	# Include a credential fingerprint so rotation takes effect without cross-site reuse.
	name = (
		"homeall-"
		+ hashlib.sha256((frappe.local.site + json.dumps(credential, sort_keys=True)).encode()).hexdigest()
	)
	try:
		app = firebase_admin.get_app(name)
	except ValueError:
		app = firebase_admin.initialize_app(
			credentials.Certificate(credential), {"httpTimeout": 15}, name=name
		)
	data = {
		"event_id": event.name,
		"type": event.event_type,
		"title": event.title,
		"body": "Open Homeall to view the details.",
		"destination": event.destination + "&homeall_event=" + event.name,
		"expires_at": str(int(datetime.fromisoformat(event.occurred_at).timestamp()) + ttl),
	}
	messaging.send(
		messaging.Message(
			token=device.get_password("token"),
			data=data,
			webpush=messaging.WebpushConfig(headers={"TTL": str(ttl), "Urgency": "high"}),
		),
		app=app,
	)


def recover():
	if not cint(settings().get("enabled")):
		return
	for name in frappe.get_all(
		EVENT, filters={"status": "Pending"}, pluck="name", limit_page_length=100, order_by="creation asc"
	):
		enqueue_event(name)
	if not cint(settings().get("push_enabled")):
		return
	rows = frappe.db.sql(
		"""select name from `tabHomeall Notification Delivery`
		where channel='Push' and
		((status='Pending' and next_attempt_at <= %s) or
		 (status='Sending' and claimed_at <= %s)) order by next_attempt_at limit 200""",
		(now_datetime(), now_datetime() - timedelta(minutes=5)),
		as_dict=True,
	)
	for row in rows:
		enqueue_delivery(row.name)


@frappe.whitelist(methods=["GET"])
def health() -> dict:
	frappe.only_for("System Manager")
	return {
		"pending_events": frappe.db.count(EVENT, {"status": "Pending"}),
		"failed_deliveries": frappe.db.count(DELIVERY, {"status": "Failed"}),
		"pending_deliveries": frappe.db.count(DELIVERY, {"status": ["in", ["Pending", "Sending"]]}),
		"oldest_pending": frappe.db.get_value(
			EVENT, {"status": "Pending"}, "creation", order_by="creation asc"
		),
	}


@frappe.whitelist(methods=["POST"])
def replay(event_id: str) -> dict:
	frappe.only_for("System Manager")
	frappe.db.set_value(
		DELIVERY,
		{"parent": event_id, "status": "Failed"},
		{
			"status": "Pending",
			"attempts": 0,
			"next_attempt_at": now_datetime(),
		},
	)
	frappe.db.after_commit.add(lambda: enqueue_event(event_id))
	return {"queued": True}
