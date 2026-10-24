import hashlib
import json
from urllib.parse import urlencode
from uuid import uuid4

import frappe
from frappe.utils import cint, now_datetime
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Response

from .policy import identifier, normalize_event, verify_signature

PREFIX = "homeall_ecommerce_integration.notifications"
PUBLIC_FIREBASE_KEYS = ("apiKey", "authDomain", "projectId", "storageBucket", "messagingSenderId", "appId")


def settings():
	value = frappe.conf.get("homeall_notifications")
	return value if isinstance(value, dict) else {}


def staff(user=None):
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	return bool(frappe.db.exists("User", {"name": user, "enabled": 1, "user_type": "System User"}))


def require_staff():
	if not staff():
		frappe.throw("Desk access is required.", frappe.PermissionError)


def session_hash():
	return hashlib.sha256(str(frappe.session.sid).encode()).hexdigest()


def public_config():
	cfg = settings()
	web = cfg.get("firebase_web_config") or {}
	return {key: web[key] for key in PUBLIC_FIREBASE_KEYS if web.get(key)}


@frappe.whitelist(methods=["GET"])
def get_config() -> dict:
	require_staff()
	cfg = settings()
	web = public_config()
	return {
		"enabled": bool(cint(cfg.get("enabled"))),
		"push_enabled": bool(cint(cfg.get("push_enabled"))),
		"firebase": web,
		"vapid_key": cfg.get("firebase_vapid_public_key") or "",
		"configured": all(web.get(key) for key in ("apiKey", "projectId", "messagingSenderId", "appId"))
		and bool(cfg.get("firebase_vapid_public_key")),
	}


@frappe.whitelist(methods=["POST"])
def register(installation_id: str, token: str) -> dict:
	require_staff()
	cfg = settings()
	if not cint(cfg.get("enabled")) or not cint(cfg.get("push_enabled")):
		frappe.throw("Browser notifications are disabled.")
	try:
		installation_id = identifier(installation_id)
	except ValueError, TypeError:
		frappe.throw("Invalid installation.")
	if not isinstance(token, str) or not 20 <= len(token) <= 4096 or any(c.isspace() for c in token):
		frappe.throw("Invalid Firebase registration.")
	fingerprint = hashlib.sha256(token.encode()).hexdigest()
	# Serialize creation, token rotation and account switches for this installation.
	with (
		frappe.cache.lock("homeall_push_registration:" + installation_id, timeout=15, blocking_timeout=5),
		frappe.cache.lock("homeall_push_token:" + fingerprint, timeout=15, blocking_timeout=5),
	):
		existing = frappe.db.get_value("Homeall Push Subscription", installation_id, "name", for_update=True)
		doc = (
			frappe.get_doc("Homeall Push Subscription", installation_id, for_update=True)
			if existing
			else frappe.new_doc("Homeall Push Subscription")
		)
		# Disable other registrations for this token. Updating the loaded document
		# here would change its modified timestamp before save() and cause Frappe's
		# optimistic concurrency check to reject every same-token page refresh.
		frappe.db.set_value(
			"Homeall Push Subscription",
			{
				"token_hash": fingerprint,
				"name": ["!=", installation_id],
			},
			"enabled",
			0,
		)
		doc.update(
			{
				"installation_id": installation_id,
				"user": frappe.session.user,
				"token": token,
				"token_hash": fingerprint,
				"enabled": 1,
				"session_hash": session_hash(),
				"last_registered_at": now_datetime(),
				"generation": doc.generation
				if doc.user == frappe.session.user and doc.token_hash == fingerprint and doc.enabled
				else str(uuid4()),
			}
		)
		doc.save(ignore_permissions=True)
		# The cache lock must cover the commit, including token ownership changes.
		frappe.db.commit()
	return {"enabled": True}


@frappe.whitelist(methods=["POST"])
def unregister(installation_id: str) -> dict:
	require_staff()
	frappe.db.set_value(
		"Homeall Push Subscription",
		{
			"name": installation_id,
			"user": frappe.session.user,
		},
		"enabled",
		0,
	)
	return {"enabled": False}


def on_logout(login_manager=None):
	if frappe.session.user != "Guest" and frappe.db.table_exists("Homeall Push Subscription"):
		frappe.db.set_value(
			"Homeall Push Subscription",
			{
				"user": frappe.session.user,
				"session_hash": session_hash(),
			},
			"enabled",
			0,
		)


def preserve_notification_login():
	"""Desk's guest redirect uses request.path and drops notification query arguments."""
	request = frappe.request
	if request.method != "GET" or frappe.session.user != "Guest":
		return
	keys = {
		"/desk/online-order": ("order", "homeall_event"),
		"/desk/chat": ("conversation", "message", "homeall_event"),
	}.get(request.path)
	if not keys or not request.args.get(keys[0]):
		return
	try:
		query = {key: identifier(request.args[key]) for key in keys if request.args.get(key)}
	except ValueError, TypeError, AttributeError:
		return
	target = request.path + "?" + urlencode(query)
	# HTTPException responses are supported by frappe.app during before_request.
	raise HTTPException(
		response=Response(
			status=302,
			headers={
				"Location": "/login?" + urlencode({"redirect-to": target}),
				"Cache-Control": "no-store",
			},
		)
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive_event(**kwargs: object) -> dict:
	cfg = settings()
	if not cint(cfg.get("enabled")):
		frappe.throw("Notification integration is disabled.", frappe.PermissionError)
	body = frappe.request.get_data(cache=True)
	if len(body) > 16384 or not verify_signature(
		cfg.get("webhook_secret"),
		frappe.get_request_header("X-Homeall-Timestamp"),
		frappe.get_request_header("X-Homeall-Signature"),
		body,
	):
		frappe.throw("Invalid notification signature.", frappe.PermissionError)
	try:
		event = normalize_event(json.loads(body))
	except ValueError, TypeError, KeyError, AttributeError:
		frappe.throw("Invalid notification event.")
	name = event["event_id"]
	# INSERT IGNORE makes simultaneous deliveries idempotent without a Redis dependency.
	frappe.db.sql(
		"""insert ignore into `tabHomeall Notification Event`
		(name, creation, modified, owner, modified_by, docstatus, idx,
		 event_id, event_type, occurred_at, payload, destination, title, status)
		values (%s, NOW(6), NOW(6), 'Administrator', 'Administrator', 0, 0,
		 %s, %s, %s, %s, %s, %s, 'Pending')""",
		(
			name,
			name,
			event["event_type"],
			event["occurred_at"],
			json.dumps(event["payload"]),
			event["destination"],
			event["title"],
		),
	)
	# Frappe's POST request commits before sending its response. Queue outages must not
	# reject an already persisted event: the minute scheduler recovers pending events.
	frappe.db.after_commit.add(lambda: enqueue_event(name))
	return {"accepted": True, "event_id": name}


def enqueue_event(name):
	try:
		frappe.enqueue(PREFIX + ".worker.process_event", event_id=name, queue="short")
	except Exception:
		frappe.logger("homeall_notifications", allow_site=True).error(
			"Event queued for scheduler recovery: %s", name
		)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def service_worker() -> Response:
	# Isolated scope avoids replacing another application's root service worker.
	from frappe.utils import get_assets_json

	manifest = get_assets_json()
	bundle = manifest.get("homeall_push_worker.bundle.js")
	if not bundle:
		return Response(
			"throw new Error('Build Homeall notification assets first');",
			status=503,
			mimetype="application/javascript",
		)
	content = (
		"self.HOMEALL_FIREBASE_CONFIG="
		+ json.dumps(public_config())
		+ ";\nimportScripts("
		+ json.dumps(bundle)
		+ ");"
	)
	return Response(
		content,
		mimetype="application/javascript",
		headers={
			"Service-Worker-Allowed": "/",
			"Cache-Control": "no-cache",
			"X-Content-Type-Options": "nosniff",
		},
	)


@frappe.whitelist(methods=["POST"])
def mark_opened(event_id: str) -> dict:
	require_staff()
	name = identifier(event_id)
	logs = frappe.get_all(
		"Homeall Notification Delivery",
		filters={
			"parent": name,
			"user": frappe.session.user,
			"channel": "Bell",
		},
		pluck="notification_log",
	)
	for log in logs:
		if log:
			frappe.db.set_value("Notification Log", {"name": log, "for_user": frappe.session.user}, "read", 1)
	frappe.publish_realtime(
		"homeall_notification_read",
		{
			"unread_count": frappe.db.count("Notification Log", {"for_user": frappe.session.user, "read": 0}),
		},
		user=frappe.session.user,
		after_commit=True,
	)
	return {"read": True}
