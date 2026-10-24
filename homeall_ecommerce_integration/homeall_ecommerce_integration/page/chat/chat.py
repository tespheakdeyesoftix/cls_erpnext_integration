"""Authenticated Desk chat API. Shared chat history remains exclusively in Supabase."""

import hashlib
import io
import json
import os
import re
import socket
import threading
import time
import warnings
from contextlib import contextmanager, suppress
from datetime import datetime
from functools import lru_cache, partial
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

import frappe
import requests
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
from werkzeug.wrappers import Response

from homeall_ecommerce_integration.r2_storage import client as r2_client
from homeall_ecommerce_integration.r2_storage.config import required as r2_required

EVENT = "homeall_chat"
BUCKET = "homeall-chat-staging"
MAX_PHOTO = 8_388_608
MIMES = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}
SEND_RPC = "api_frappe_admin_chat_send_message"
SHARED_SEND_RPC = "api_admin_chat_send_message"
SEND_PARAMETERS = {
	"p_user",
	"p_conversation",
	"p_client_message",
	"p_kind",
	"p_sender_display_name",
	"p_body",
	"p_media_key",
	"p_media_type",
	"p_media_size",
}
READ_ROLES = {"owner", "manager", "operator", "viewer"}
REPLY_ROLES = READ_ROLES - {"viewer"}
_http = threading.local()


class ChatHTTPSConnection(HTTPSConnection):
	def _new_conn(self):
		hostname = self._dns_host
		try:
			addresses = socket.getaddrinfo(hostname, self.port, socket.AF_INET, socket.SOCK_STREAM)
		except socket.gaierror:
			return super()._new_conn()
		failure = None
		try:
			for address in dict.fromkeys(row[4][0] for row in addresses):
				self._dns_host = address
				try:
					return super()._new_conn()
				except (ConnectTimeoutError, NewConnectionError) as error:
					failure = error
			if failure is not None:
				raise failure
		finally:
			# TLS/SNI, certificate checks and HTTP Host must use the original hostname.
			self._dns_host = hostname
		return super()._new_conn()


class ChatHTTPSConnectionPool(HTTPSConnectionPool):
	ConnectionCls = ChatHTTPSConnection


class ChatHTTPAdapter(requests.adapters.HTTPAdapter):
	"""Prefer A-record lookup without changing DNS or connection behavior for other apps."""

	def init_poolmanager(self, *args, **kwargs):
		super().init_poolmanager(*args, **kwargs)
		self.poolmanager.pool_classes_by_scheme = {
			**self.poolmanager.pool_classes_by_scheme,
			"https": ChatHTTPSConnectionPool,
		}

	def proxy_manager_for(self, *args, **kwargs):
		manager = super().proxy_manager_for(*args, **kwargs)
		manager.pool_classes_by_scheme = {**manager.pool_classes_by_scheme, "https": ChatHTTPSConnectionPool}
		return manager


@lru_cache(maxsize=1)
def http_adapter(pid):
	"""Share connection pools across request threads, with a separate pool after a fork."""
	return ChatHTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=0)


def http_session():
	"""Keep cookies and headers thread-local while reusing the process's TLS connections."""
	pid = os.getpid()
	if getattr(_http, "pid", None) != pid:
		if getattr(_http, "session", None):
			_http.session.close()
		_http.session = requests.Session()
		_http.session.mount("https://", http_adapter(pid))
		_http.pid = pid
	return _http.session


@contextmanager
def timing(name):
	started = time.perf_counter()
	try:
		yield
	finally:
		if (headers := getattr(frappe.local, "response_headers", None)) is not None:
			headers.add("Server-Timing", f"{name};dur={(time.perf_counter() - started) * 1000:.1f}")


def fail(message, permission=False):
	frappe.throw(message, frappe.PermissionError if permission else frappe.ValidationError)


def uuid(value):
	try:
		return str(UUID(str(value)))
	except ValueError, TypeError, AttributeError:
		fail("Invalid chat identifier.")


def role_names(reply=False):
	value = frappe.conf.get("chat_reply_roles" if reply else "chat_read_roles")
	if value is None:
		return {"System Manager"}
	if not isinstance(value, list) or not all(isinstance(role, str) for role in value):
		fail("Chat roles must be configured as a list.")
	return set(value)


def allowed_user(user, reply=False):
	if not user or user == "Guest":
		return False
	info = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not info or not info.enabled or info.user_type != "System User":
		return False
	return not reply or bool(set(frappe.get_roles(user)) & role_names(True))


def require_staff(reply=False):
	if not allowed_user(frappe.session.user) or (reply and not allowed_user(frappe.session.user, True)):
		fail("You do not have permission to access or reply to support chats.", True)


def recipients():
	return [
		u
		for u in frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name")
		if allowed_user(u)
	]


def supabase_config():
	url = (frappe.conf.get("supabase_url") or "").rstrip("/")
	parsed = urlsplit(url)
	if (
		parsed.scheme != "https"
		or not parsed.hostname
		or parsed.username
		or parsed.password
		or parsed.query
		or parsed.fragment
	):
		fail("Configure a valid HTTPS supabase_url on the server.")
	key = frappe.conf.get("supabase_service_role_key") or ""
	if not key or key.startswith("sb_publishable_"):
		key = None
		fail("Configure a server-side Supabase secret or service-role key.")
	try:
		admin = str(UUID(str(frappe.conf.get("supabase_admin_user_id"))))
	except ValueError, TypeError, AttributeError:
		key = None
		fail("Configure supabase_admin_user_id as the active Supabase admin's UUID on the server.")
	return url, key, admin


def redacted_error(error, secret):
	"""Retain PostgREST diagnostics server-side, without credential values."""
	if isinstance(error, dict):
		return {
			k: "[REDACTED]"
			if str(k).lower() in {"apikey", "authorization", "access_token", "refresh_token"}
			else redacted_error(v, secret)
			for k, v in error.items()
		}
	if isinstance(error, list):
		return [redacted_error(value, secret) for value in error]
	if isinstance(error, str):
		if secret:
			error = error.replace(secret, "[REDACTED]")
		error = re.sub(r"sb_(?:secret|publishable)_[A-Za-z0-9_-]+", "[REDACTED]", error)
		return re.sub(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", error)
	return error


def log_request_failure(path, payload, status, error, duration_ms=None):
	# Log parameter NAMES only. Never log the request body, authorization headers or key.
	diagnostic = {
		"project_host": urlsplit(frappe.conf.get("supabase_url") or "").hostname,
		"path": path,
		"parameter_names": sorted(payload) if isinstance(payload, dict) else [],
		"status": status,
		"postgrest_error": error,
		"duration_ms": duration_ms,
	}
	frappe.logger("homeall_chat", allow_site=True).error(json.dumps(diagnostic, ensure_ascii=True))


def request(path, payload=None, params=None):
	url, key, _ = supabase_config()
	headers = {"apikey": key}
	# A new sb_secret_ API key is not a bearer JWT. The gateway authenticates apikey.
	if not key.startswith("sb_"):
		headers["Authorization"] = f"Bearer {key}"
	problem = False
	response = None
	diagnostic = {"message": "Connection failed or invalid JSON response."}
	status = None
	started = time.monotonic()
	try:
		with timing("chat_remote"):
			response = http_session().request(
				"POST" if payload is not None else "GET",
				url + "/rest/v1/" + path,
				headers=headers,
				json=payload,
				params=params,
				timeout=(5, 30),
			)
		if response.ok:
			return response.json()
		status = response.status_code
		try:
			diagnostic = response.json()
		except ValueError:
			diagnostic = {"message": "Non-JSON error response; response body omitted."}
		diagnostic = redacted_error(diagnostic, key)
		problem = True
	except (requests.RequestException, ValueError) as error:
		diagnostic = {
			"message": "Connection failed or invalid JSON response.",
			"error_type": type(error).__name__,
		}
		problem = True
	# Full redacted PostgREST diagnostics stay on the server; only useful generic guidance
	# reaches the browser. Never infer physical function absence from a cache lookup error.
	if problem:
		# Also remove secrets from locals before Frappe can collect a contextual traceback.
		key = headers = response = None
		log_request_failure(path, payload, status, diagnostic, round((time.monotonic() - started) * 1000))
		if isinstance(diagnostic, dict) and diagnostic.get("code") == "PGRST202":
			fail(
				"The chat RPC parameters do not match the Supabase schema cache. Verify the staff-alias migration and reload the PostgREST schema cache. See the server chat log for details."
			)
		fail("Chat service is unavailable or rejected this operation. Retry or contact your administrator.")


def rpc(name, **params):
	return request("rpc/" + name, {**params, "p_user": supabase_config()[2]})


def admin_role():
	admin = supabase_config()[2]
	profiles = request("profiles", params={"id": "eq." + admin, "select": "status", "limit": 1})
	memberships = request("admin_memberships", params={"user_id": "eq." + admin, "select": "role,status"})
	if not profiles or str(profiles[0].get("status", "")).lower() != "active":
		fail("The configured Supabase admin profile must be active.", True)
	roles = {m.get("role") for m in memberships if str(m.get("status", "")).lower() == "active"}
	if not roles & READ_ROLES:
		fail("The configured Supabase admin membership must be active.", True)
	return roles


def authorize(reply=False, before_upload=False):
	# Every data RPC already checks the configured admin's active profile, membership,
	# conversation access and reply role inside its transaction. Do not precede each
	# RPC with two more network requests. Frappe permissions are always checked here.
	require_staff(reply)
	# R2 is an external side effect before the send transaction, so photo uploads
	# also verify the remote reply role before writing any object.
	if before_upload and not admin_role() & REPLY_ROLES:
		fail("The Supabase admin membership is read-only.", True)


def cursor_params(cursor):
	if isinstance(cursor, str):
		try:
			cursor = json.loads(cursor)
		except ValueError:
			fail("Invalid chat cursor.")
	if not cursor:
		return {"p_before": None, "p_before_id": None}
	if not isinstance(cursor, dict) or not cursor.get("created_at") or not cursor.get("id"):
		fail("Both chat cursor fields are required.")
	try:
		datetime.fromisoformat(cursor["created_at"].replace("Z", "+00:00"))
	except ValueError, TypeError, AttributeError:
		fail("Invalid chat cursor timestamp.")
	return {"p_before": cursor["created_at"], "p_before_id": uuid(cursor["id"])}


def capabilities():
	cache = frappe.cache()
	key = "homeall_chat:capabilities:staff_alias_v2"
	result = cache.get_value(key)
	if result is None:
		schema = request("")
		columns = schema.get("definitions", {}).get("chat_messages", {}).get("properties", {})
		parameters = schema.get("paths", {}).get("/rpc/" + SEND_RPC, {}).get("post", {}).get("parameters", [])
		accepts_alias = False
		for parameter in parameters:
			if parameter.get("in") != "body":
				continue
			body = parameter.get("schema", {})
			if "$ref" in body:
				body = schema.get("definitions", {}).get(body["$ref"].rsplit("/", 1)[-1], {})
			accepts_alias = SEND_PARAMETERS <= body.get("properties", {}).keys()
			if accepts_alias:
				break
		result = {
			"aliases": "sender_display_name" in columns,
			"send_rpc": accepts_alias,
			"frappe_send_rpc": "/rpc/" + SEND_RPC in schema.get("paths", {}),
			"shared_send_rpc": "/rpc/" + SHARED_SEND_RPC in schema.get("paths", {}),
		}
		cache.set_value(key, result, expires_in_sec=60)
	return result


def send_setup_notice(cap):
	if not cap.get("shared_send_rpc"):
		return "The shared chat send RPC is not exposed in this Supabase project's schema cache. Verify 20261003001900_business_chat.sql, service-role grants and the schema cache; do not create a replacement function."
	if not cap.get("aliases") or not cap.get("frappe_send_rpc"):
		return "Staff-name support is not exposed in this Supabase project's schema cache. Verify installation of 20261023000100_frappe_chat_staff_alias.sql and reload the PostgREST schema cache."
	if not cap.get("send_rpc"):
		return "The Frappe staff-alias RPC parameters do not match the expected contract. Verify the deployed migration and PostgREST schema cache."
	return None


def require_send_ready():
	notice = send_setup_notice(capabilities())
	if notice:
		fail(notice)


def bridge_health():
	health = frappe.cache().get_value("homeall_chat:health") or {}
	return {"status": health.get("status", "Offline"), "updated_at": health.get("updated_at")}


@frappe.whitelist(methods=["POST"])
def bootstrap(include_inbox: bool = False) -> dict:
	authorize()
	roles = admin_role()
	cap = capabilities()
	can_reply = allowed_user(frappe.session.user, True) and bool(roles & REPLY_ROLES)
	notice = send_setup_notice(cap)
	result = {
		"can_send": can_reply and notice is None,
		"display_name": staff_name(),
		"health": bridge_health(),
		"setup_notice": notice,
	}
	if include_inbox:
		result["inbox"] = conversation_page()
	return result


def staff_name():
	name = frappe.db.get_value("User", frappe.session.user, "full_name")
	if not isinstance(name, str) or not name.strip():
		name = frappe.session.user
	name = name.strip()
	if not 1 <= len(name) <= 255:
		fail(
			"Your Frappe staff display name must contain 1-255 characters after trimming. Update your User full name before replying."
		)
	return name


@frappe.whitelist(methods=["POST"])
def conversations(search: str = "", unread: bool = False, cursor: dict | str | None = None) -> dict:
	authorize()
	return conversation_page(search, unread, cursor)


def conversation_page(search="", unread=False, cursor=None):
	return rpc(
		"api_admin_chat_conversations",
		p_search=search.strip()[:200] or None,
		p_unread=frappe.utils.cint(unread) == 1,
		p_limit=50,
		**cursor_params(cursor),
	)


def media_url(message_id):
	return "/api/method/" + __name__ + ".media?message_id=" + uuid(message_id)


def present_message(message):
	item = {
		k: message.get(k)
		for k in (
			"id",
			"conversation_id",
			"sender_user_id",
			"sender_role",
			"kind",
			"body",
			"media_content_type",
			"media_size_bytes",
			"client_message_id",
			"created_at",
			"sender_display_name",
		)
	}
	if not isinstance(item["sender_display_name"], str):
		item["sender_display_name"] = None
	if item["kind"] == "photo":
		item["media_url"] = media_url(item["id"])
	return item


@frappe.whitelist(methods=["POST"])
def messages(conversation_id: str, cursor: dict | str | None = None) -> dict:
	authorize()
	result = rpc(
		"api_admin_chat_messages", p_conversation=uuid(conversation_id), p_limit=100, **cursor_params(cursor)
	)
	items = result.get("items") or []
	# Existing history serializers may enumerate columns. Enrich saved aliases without rewriting them.
	missing_aliases = [m for m in items if "sender_display_name" not in m]
	if missing_aliases and capabilities()["aliases"]:
		ids = ",".join(uuid(m["id"]) for m in missing_aliases)
		aliases = request(
			"chat_messages", params={"id": "in.(" + ids + ")", "select": "id,sender_display_name"}
		)
		lookup = {m["id"]: m.get("sender_display_name") for m in aliases}
		for item in missing_aliases:
			if item["id"] in lookup:
				item["sender_display_name"] = lookup[item["id"]]
	result["items"] = [present_message(m) for m in items]
	return result


def publish(payload):
	for user in recipients():
		frappe.publish_realtime(EVENT, payload, user=user, after_commit=False)


def publish_safely(payload, after_response=False):
	request = getattr(frappe.local, "request", None)
	callbacks = getattr(request, "after_response", None)
	if after_response and callbacks is not None:
		callbacks.add(partial(publish_safely, payload))
		return
	# Supabase has committed by this point. A Socket.IO/Redis failure must not turn
	# a successful send/read into an HTTP failure or invite a duplicate retry.
	try:
		publish(payload)
	except Exception:
		with suppress(Exception):
			frappe.logger("homeall_chat", allow_site=True).error(
				"Chat data saved; local realtime notification failed."
			)


@frappe.whitelist(methods=["POST"])
def mark_read(conversation_id: str, message_id: str) -> dict:
	authorize()
	result = rpc("api_chat_mark_read", p_conversation=uuid(conversation_id), p_message=uuid(message_id))
	publish_safely(
		{"event": "read_updated", "conversation_id": uuid(conversation_id), "message_id": uuid(message_id)}
	)
	return result


def save_message(
	conversation_id, client_message_id, kind, body=None, media_key=None, media_type=None, media_size=None
):
	# The RPC is the authoritative authorization/contract check. Do not download
	# OpenAPI metadata when a text send happens just after the capability cache expires.
	# Photo uploads separately check readiness before writing an R2 object.
	result = rpc(
		SEND_RPC,
		p_conversation=conversation_id,
		p_client_message=client_message_id,
		p_kind=kind,
		p_body=body,
		p_media_key=media_key,
		p_media_type=media_type,
		p_media_size=media_size,
		p_sender_display_name=staff_name(),
	)
	if isinstance(result, list):
		result = result[0]
	publish_safely(
		{"event": "message_created", "conversation_id": conversation_id, "message_id": uuid(result["id"])},
		after_response=True,
	)
	return present_message(result)


@frappe.whitelist(methods=["POST"])
def send_text(conversation_id: str, client_message_id: str, body: str) -> dict:
	with timing("chat_send"):
		with timing("chat_auth"):
			authorize(True)
		if not isinstance(body, str) or not body.strip() or len(body) > 4000:
			fail("Enter a message between 1 and 4,000 characters.")
		return save_message(uuid(conversation_id), uuid(client_message_id), "text", body=body)


def photo_config():
	# Reuse existing R2 credentials and client without requiring a PUBLIC bucket URL.
	return SimpleNamespace(
		account_id=r2_required("account_id"),
		access_key_id=r2_required("access_key_id"),
		secret_access_key=r2_required("secret_access_key"),
		bucket=BUCKET,
	)


def validate_photo(content):
	from PIL import Image

	if not content or len(content) > MAX_PHOTO:
		fail("Photos must be no larger than 8 MiB.")
	valid = False
	try:
		with warnings.catch_warnings():
			warnings.simplefilter("error", Image.DecompressionBombWarning)
			with Image.open(io.BytesIO(content)) as image:
				format_name = image.format
				if format_name in MIMES and image.width * image.height <= 40_000_000:
					image.verify()
					valid = True
			# Decode as well as checking the container to reject truncated/corrupt payloads.
			if valid:
				with Image.open(io.BytesIO(content)) as image:
					image.load()
	except Exception:
		valid = False
	if not valid:
		fail("Upload a valid JPEG, PNG, or WebP photo (maximum 40 megapixels).")
	return MIMES[format_name]


@frappe.whitelist(methods=["POST"])
def send_photo(conversation_id: str, client_message_id: str) -> dict:
	authorize(True, before_upload=True)
	conversation_id, client_message_id = uuid(conversation_id), uuid(client_message_id)
	# Authorize the specific conversation before reading bytes or uploading anything.
	rpc("api_admin_chat_messages", p_conversation=conversation_id, p_before=None, p_before_id=None, p_limit=1)
	require_send_ready()
	staff_name()  # Validate before uploading bytes; save_message derives it again for the RPC.
	file = frappe.request.files.get("file")
	if not file:
		fail("Choose a photo to attach.")
	content = file.stream.read(MAX_PHOTO + 1)
	mime, extension = validate_photo(content)
	key = f"chat/{conversation_id}/{client_message_id}-{hashlib.sha256(content).hexdigest()[:24]}.{extension}"
	failed = False
	try:
		r2_client.get_client(photo_config()).put_object(
			Bucket=BUCKET,
			Key=key,
			Body=content,
			ContentType=mime,
			CacheControl="private, no-store",
			Metadata=r2_client.ownership(),
		)
	except Exception:
		failed = True
	if failed:
		fail("Photo upload failed. Retry the same attachment.")
	# Never delete on uncertain RPC outcomes: the transaction may already have committed.
	return save_message(
		conversation_id, client_message_id, "photo", media_key=key, media_type=mime, media_size=len(content)
	)


@frappe.whitelist(methods=["GET"])
def media(message_id: str) -> Response:
	authorize()
	info = rpc("api_chat_media", p_message=uuid(message_id))
	if isinstance(info, list):
		info = info[0]
	key = info.get("object_key", "")
	if not re.fullmatch(r"chat/[0-9a-f-]{36}/[0-9a-f-]{36}-[0-9a-f]{24}\.(jpg|png|webp)", key):
		fail("Invalid chat photo reference.")
	if info.get("content_type") not in {v[0] for v in MIMES.values()}:
		fail("Unsupported chat photo.")
	failed = False
	try:
		obj = r2_client.get_client(photo_config()).get_object(Bucket=BUCKET, Key=key)
		with obj["Body"] as stream:
			content = stream.read(MAX_PHOTO + 1)
		if len(content) > MAX_PHOTO:
			raise ValueError
	except Exception:
		failed = True
	if failed:
		fail("Chat photo is unavailable. Try opening it again.")
	return Response(
		content,
		content_type=info["content_type"],
		headers={
			"Content-Disposition": "inline; filename=chat-photo." + key.rsplit(".", 1)[1],
			"Cache-Control": "private, no-store",
			"X-Content-Type-Options": "nosniff",
		},
	)
