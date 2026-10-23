"""A private, durable cleanup journal bridges database and object-store transactions.

Upload intents are written BEFORE PUT, including ambiguous network failures. Commit,
rollback, and an hourly crash/savepoint recovery pass reconcile them against File rows.
The journal contains object identities only, never credentials or image bytes.
"""

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import frappe

from . import client
from .config import fail, get_config, setting
from .utils import managed_key, object_key


def journal_dir():
	path = Path(frappe.get_site_path("private", "r2_cleanup"))
	path.mkdir(mode=0o700, parents=True, exist_ok=True)
	return path


def write_intent(config, key, action, local_url=None):
	path = journal_dir() / f"{uuid4().hex}.json"
	data = {
		"account_id": config.account_id,
		"bucket": config.bucket,
		"public_url": config.public_url,
		"prefix": config.prefix,
		"key": key,
		"action": action,
		"local_url": local_url,
		"created": time.time(),
	}
	with path.open("x", encoding="utf-8") as stream:
		json.dump(data, stream)
		stream.flush()
		os.fsync(stream.fileno())
	return path


def lock_name(config, key):
	identity = f"{config.account_id}/{config.bucket}/{key}"
	return "homeall-r2:" + hashlib.sha256(identity.encode()).hexdigest()


@contextmanager
def object_lock(config, key):
	name = lock_name(config, key)
	if name in (getattr(frappe.local, "r2_reference_locks", None) or {}):
		yield
	else:
		with frappe.cache.lock(name, timeout=600, blocking_timeout=10):
			yield


def protect_reference(config, key):
	"""Serialize URL reuse with deletion until the referencing transaction settles."""
	locks = getattr(frappe.local, "r2_reference_locks", None)
	if locks is None:
		locks = frappe.local.r2_reference_locks = {}
	name = lock_name(config, key)
	if name in locks:
		return
	lock = frappe.cache.lock(name, timeout=600, blocking_timeout=10)
	if not lock.acquire():
		fail("This R2 image is being updated. Please retry the attachment.")
	locks[name] = lock

	def release():
		if locks.pop(name, None) is not None and lock.owned():
			lock.release()

	frappe.db.after_commit.add(release)
	frappe.db.after_rollback.add(release)
	valid = False
	try:
		valid = client.owned_object(config, key)
	except Exception:
		pass
	if not valid:
		fail("The managed R2 image is missing or unavailable. Upload the image again.")


def cleanup_local(url):
	if not url or not url.startswith("/files/"):
		return
	if frappe.db.exists("File", {"file_url": url}):
		return
	root = Path(frappe.get_site_path("public", "files")).resolve()
	path = (root / url.removeprefix("/files/")).resolve()
	if not path.is_relative_to(root) or path == root:
		return
	# A backfilled v2 blob can still own the legacy path even without a File URL reference.
	if frappe.db.exists("DocType", "File Blob") and frappe.db.exists(
		"File Blob", {"driver": "local", "key": url.removeprefix("/files/"), "is_private": 0}
	):
		return
	path.unlink(missing_ok=True)


def reconcile(path):
	"""Keep failed work for retry. Never raise SDK errors into transaction callbacks."""
	try:
		data = json.loads(path.read_text())
		config = get_config()
		if not config or (data["account_id"], data["bucket"]) != (config.account_id, config.bucket):
			return  # Old bucket/account: retain the journal for explicit operator recovery.
		# Preserve the upload-time URL/prefix if configuration changed within this bucket.
		config = replace(config, public_url=data["public_url"], prefix=data["prefix"])
		url = f"{config.public_url}/{data['key']}"
		if managed_key(config, url) != data["key"]:
			return
		with object_lock(config, data["key"]):
			# A locking read sees newly committed references even if an earlier callback
			# already established a repeatable-read snapshot on this DB connection.
			if frappe.db.get_value("File", {"file_url": url}, "name", for_update=True):
				if data["action"] == "upload":
					cleanup_local(data.get("local_url"))
				path.unlink(missing_ok=True)
				return
			if data["action"] == "upload" or config.delete_on_file_delete:
				client.delete_owned(config, data["key"])
			if data["action"] == "upload":
				cleanup_local(data.get("local_url"))
		path.unlink(missing_ok=True)
	except Exception:
		# No traceback: SDK arguments, request signatures, and site config are sensitive.
		frappe.logger("r2_storage").warning("R2 cleanup pending; the hourly recovery task will retry.")


def store(config, folder, content, image_format, local_url=None):
	extension, mime = image_format
	key = object_key(config, folder, extension)
	path = write_intent(config, key, "upload", local_url)
	frappe.db.after_rollback.add(lambda: reconcile(path))
	frappe.db.after_commit.add(lambda: reconcile(path))
	client.upload(config, key, content, mime)
	return f"{config.public_url}/{key}"


def delete_after_commit(url):
	base = setting("public_url")
	if not base or not url or not url.startswith(base.rstrip("/") + "/"):
		return
	config = get_config()
	if not config or not config.delete_on_file_delete or not (key := managed_key(config, url)):
		return
	path = write_intent(config, key, "delete")
	frappe.db.after_commit.add(lambda: reconcile(path))
	frappe.db.after_rollback.add(lambda: path.unlink(missing_ok=True))


def recover_pending():
	"""Hourly retry, with 24 hours' grace for interrupted requests/savepoint rollbacks.

	Share the site's private directory across web/worker hosts. Full rollback callbacks
	run immediately; grace is only for crash recovery and partial/savepoint rollbacks.
	"""
	for path in journal_dir().glob("*.json"):
		try:
			if time.time() - path.stat().st_mtime >= 86400:
				reconcile(path)
		except FileNotFoundError:
			continue  # A request/another worker reconciled it first.
