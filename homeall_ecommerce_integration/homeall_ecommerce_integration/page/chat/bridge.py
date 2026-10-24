"""One persistent private Supabase Broadcast -> Frappe Socket.IO bridge per site.

Run from the bench directory:
  env/bin/python -m homeall_ecommerce_integration.homeall_ecommerce_integration.page.chat.bridge --site SITE
"""

import argparse
import asyncio
import contextlib
import logging
import os
import random
import signal
import threading
import time
from pathlib import Path
from uuid import UUID

import frappe

from . import chat


def identifier(value):
	try:
		return str(UUID(str(value)))
	except ValueError, TypeError, AttributeError:
		return None


def identifiers(event, envelope):
	payload = envelope.get("payload", envelope)
	message = payload.get("message") or {}
	conversation = payload.get("conversation") or {}
	conversation_id = identifier(
		payload.get("conversation_id") or message.get("conversation_id") or conversation.get("id")
	)
	if not conversation_id:
		return None
	return {
		"event": event,
		"conversation_id": conversation_id,
		"message_id": identifier(message.get("id") or payload.get("message_id")),
	}


def fresh_site():
	"""A worker's request cache and database snapshot must not outlive permission changes."""
	site, sites_path = frappe.local.site, frappe.local.sites_path
	frappe.destroy()
	frappe.init(site=site, sites_path=sites_path)
	frappe.connect()


def site_job(site, sites_path, callback, *args):
	"""Run blocking Frappe/HTTP work with its own site context and database connection."""
	try:
		frappe.init(site=site, sites_path=sites_path, force=True)
		frappe.connect()
		return callback(*args)
	finally:
		frappe.destroy()


async def site_call(callback, *args):
	# Keep the websocket listener and heartbeat responsive during slow REST calls.
	return await asyncio.to_thread(site_job, frappe.local.site, frappe.local.sites_path, callback, *args)


def heartbeat():
	fresh_site()
	frappe.cache().set_value(
		"homeall_chat:health", {"status": "Live", "updated_at": int(time.time())}, expires_in_sec=30
	)
	chat.publish({"event": "bridge_heartbeat", "status": "Live"})


def health(status):
	fresh_site()
	payload = {"status": status, "updated_at": int(time.time())}
	frappe.cache().set_value("homeall_chat:health", payload, expires_in_sec=30)
	chat.publish({"event": "bridge_status", **payload})


def notify_customer_message(conversation_id, message_id):
	"""Verify the stored sender and current permissions in the notification worker."""
	from homeall_ecommerce_integration.notifications.api import settings
	from frappe.utils import cint

	if cint(settings().get("enabled")):
		return  # The durable webhook pipeline owns both bell and push delivery.
	conversation_id, message_id = chat.uuid(conversation_id), chat.uuid(message_id)
	chat.admin_role()
	rows = chat.request(
		"chat_messages",
		params={
			"id": "eq." + message_id,
			"conversation_id": "eq." + conversation_id,
			"select": "sender_role",
			"limit": 1,
		},
	)
	if not rows or rows[0]["sender_role"] != "customer":
		return
	users = chat.recipients()
	if not users:
		return
	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	enqueue_create_notification(
		users,
		{
			"type": "Alert",
			"subject": "New support chat message",
			"app": "homeall_ecommerce_integration",
			"link": f"/app/chat?conversation={conversation_id}&message={message_id}",
		},
		dedupe_on=["link"],
	)


def deliver(event, envelope, ensure_lease=lambda: None):
	data = identifiers(event, envelope)
	if not data:
		return
	fresh_site()
	cache = frappe.cache()
	# A context may legitimately change back to the same snapshot; dedupe briefly only.
	identity = data["message_id"] if event == "message_created" else None
	if identity:
		key = cache.make_key("homeall_chat:message:" + identity)
		if not cache.set(key, "1", nx=True, ex=86400):
			return
	try:
		users = chat.recipients()
		for user in users:
			ensure_lease()
			frappe.publish_realtime(chat.EVENT, data, user=user, after_commit=False)
	except Exception:
		if identity:
			cache.delete(key)
		frappe.db.rollback()
		raise
	if identity and users:
		try:
			frappe.enqueue(
				"homeall_ecommerce_integration.homeall_ecommerce_integration.page.chat.bridge.notify_customer_message",
				queue="short",
				conversation_id=data["conversation_id"],
				message_id=identity,
				job_id="homeall_chat_notification:" + identity,
				deduplicate=True,
			)
		except Exception:
			frappe.logger("homeall_chat", allow_site=True).error(
				"Live chat update delivered; bell notification could not be queued for message %s.", identity
			)


async def consume(stop):
	from realtime import AsyncRealtimeClient

	cache = frappe.cache()
	lock = cache.lock(
		cache.make_key("homeall_chat:bridge"), timeout=30, blocking_timeout=0, thread_local=False
	)
	if not lock.acquire(blocking=False):
		raise RuntimeError("A chat bridge is already running for this site.")
	queue = asyncio.Queue(maxsize=2000)
	client = None
	backoff = 1
	renewal_stop, lease_lost = threading.Event(), threading.Event()

	def renew():
		# No Frappe context in this thread. Keep the lease alive during blocking HTTP/DB I/O.
		while not renewal_stop.wait(5):
			try:
				lock.extend(30, replace_ttl=True)
			except Exception:
				lease_lost.set()
				return

	def ensure_lease():
		if lease_lost.is_set() or not lock.owned():
			raise RuntimeError("Chat bridge lease was lost.")

	renewer = threading.Thread(target=renew, name="chat-lease", daemon=True)
	renewer.start()
	try:
		await site_call(chat.admin_role)
		while not stop.is_set():
			ensure_lease()
			try:
				await site_call(health, "Connecting" if backoff == 1 else "Reconnecting")
				url, key, _ = chat.supabase_config()
				client = AsyncRealtimeClient(
					url + "/realtime/v1", token=key, auto_reconnect=False, timeout=10
				)
				# Verified against the deployed gateway: sb_secret apikey authenticates private
				# joins without being sent as an invalid JWT in access_token.
				access_token = frappe.conf.get("supabase_realtime_access_token")
				await client.set_auth(access_token or (None if key.startswith("sb_") else key))
				joined = asyncio.Event()
				failed = asyncio.Event()
				channel = client.channel("chat:admin", {"config": {"private": True}})

				def incoming(event, payload):
					try:
						queue.put_nowait((event, payload))
					except asyncio.QueueFull:
						failed.set()  # Reconnect/catch-up instead of silently dropping updates.

				for event in ("message_created", "context_updated"):
					channel.on_broadcast(event, lambda p, e=event: incoming(e, p))

				def state(status, error):
					if getattr(status, "value", status) == "SUBSCRIBED":
						joined.set()
					else:
						failed.set()

				await channel.subscribe(state)
				await asyncio.wait_for(joined.wait(), timeout=15)
				await site_call(health, "Live")  # Every successful join causes a one-time browser catch-up.
				backoff = 1
				last_health = time.monotonic()
				while not stop.is_set() and client.is_connected and not failed.is_set():
					ensure_lease()
					if time.monotonic() - last_health >= 10:
						# Health lease only: no database/inbox polling.
						await site_call(heartbeat)
						last_health = time.monotonic()
					try:
						event, payload = await asyncio.wait_for(queue.get(), timeout=1)
						await site_call(deliver, event, payload, ensure_lease)
					except TimeoutError:
						pass
				if not stop.is_set():
					raise ConnectionError
			except Exception:
				ensure_lease()
				# Never log exception details: websocket URLs contain the API key.
				await site_call(health, "Reconnecting")
				print(
					"Chat bridge reconnecting; service or private-channel authentication unavailable.",
					flush=True,
				)
			finally:
				if client:
					with contextlib.suppress(Exception):
						await client.close()
					client = None
			if not stop.is_set():
				# Bail out if lease renewal failed while waiting to reconnect.
				for _ in range(int(backoff + random.random()) + 1):
					ensure_lease()
					try:
						await asyncio.wait_for(stop.wait(), timeout=1)
						break
					except TimeoutError:
						pass
				backoff = min(backoff * 2, 30)
	finally:
		try:
			if lock.owned():
				await site_call(health, "Offline")
				lock.release()
		finally:
			renewal_stop.set()
			renewer.join(timeout=2)


async def run():
	stop = asyncio.Event()
	loop = asyncio.get_running_loop()
	for signum in (signal.SIGINT, signal.SIGTERM):
		loop.add_signal_handler(signum, stop.set)
	await consume(stop)


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--site", required=True)
	parser.add_argument("--sites-path", default="sites")
	args = parser.parse_args()
	# Frappe logging and site utilities expect the working directory to be sites/.
	sites_path = Path(args.sites_path).resolve()
	os.chdir(sites_path)
	# Third-party debug logs can contain websocket URL query credentials.
	for name in ("realtime", "websockets", "httpx", "httpcore", "urllib3"):
		logging.getLogger(name).setLevel(logging.CRITICAL)
	try:
		frappe.init(site=args.site, sites_path=".")
		frappe.connect()
		asyncio.run(run())
	except Exception:
		print(
			"Chat bridge stopped. Check configuration, Redis, database, and duplicate instances.", flush=True
		)
		raise SystemExit(1) from None
	finally:
		frappe.destroy()


if __name__ == "__main__":
	main()
