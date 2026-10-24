"""Pure validation shared by the webhook and offline tests."""

import hashlib
import hmac
import time
from datetime import UTC, datetime, timezone
from uuid import UUID


def identifier(value):
	return str(UUID(str(value)))


def verify_signature(secret, timestamp, signature, body, now=None):
	try:
		if not secret or abs((time.time() if now is None else now) - int(timestamp)) > 300:
			return False
		expected = hmac.new(
			secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256
		).hexdigest()
		return hmac.compare_digest(expected, str(signature))
	except ValueError, TypeError, AttributeError:
		return False


def normalize_event(value):
	if not isinstance(value, dict):
		raise ValueError("Invalid event")
	event_id = identifier(value["id"])
	kind = value["type"]
	if kind not in {"order_created", "chat_message"}:
		raise ValueError("Unsupported event")
	created = datetime.fromisoformat(value["created_at"].replace("Z", "+00:00"))
	if created.tzinfo is None or created.timestamp() > time.time() + 300:
		raise ValueError("Invalid event time")
	payload = value["payload"]
	if kind == "order_created":
		payload = {"order_id": identifier(payload["order_id"])}
		path = "/desk/online-order?order=" + payload["order_id"]
		title = "New online order"
	else:
		payload = {key: identifier(payload[key]) for key in ("conversation_id", "message_id")}
		path = "/desk/chat?conversation=" + payload["conversation_id"] + "&message=" + payload["message_id"]
		title = "New customer message"
	return {
		"event_id": event_id,
		"event_type": kind,
		"occurred_at": created.astimezone(UTC).isoformat(),
		"payload": payload,
		"destination": path,
		"title": title,
	}


def delivery_key(event_id, user, subscription="bell"):
	return hashlib.sha256(f"{event_id}\n{user}\n{subscription}".encode()).hexdigest()


def expired(occurred_at, ttl, now=None):
	return (time.time() if now is None else now) >= datetime.fromisoformat(occurred_at).timestamp() + ttl
