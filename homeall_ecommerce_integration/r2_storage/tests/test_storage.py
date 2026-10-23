"""Offline tests: python -m unittest homeall_ecommerce_integration.r2_storage.tests.test_storage"""

import base64
import io
import json
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from frappe.model.document import Document
from PIL import Image

from homeall_ecommerce_integration.r2_storage import client, config, file_handler, storage, utils

SETTINGS = {
	"enabled": True,
	"account_id": "a" * 32,
	"access_key_id": "b" * 32,
	"secret_access_key": "c" * 64,
	"bucket": "test-images",
	"public_url": "https://images.example.com",
	"key_prefix": "",
	"max_file_size_mb": 10,
	"delete_on_file_delete": False,
}
HOOKS = {
	"Item": {"folder": ["items"]},
	"Customer": {"folder": ["customers"]},
	"Supplier": {"folder": ["suppliers"]},
}
REAL_GET_CLIENT = client.get_client


class ValidationFailure(Exception):
	pass


def image_bytes(format="PNG"):
	stream = io.BytesIO()
	Image.new("RGB", (4, 4), "red").save(stream, format=format)
	return stream.getvalue()


class Callbacks:
	def __init__(self):
		self.callbacks = []

	def add(self, fn):
		self.callbacks.append(fn)

	def run(self):
		callbacks, self.callbacks = self.callbacks, []
		for fn in callbacks:
			fn()


class CoreFile(Document):
	def save_file(self, *args, **kwargs):
		self.fallback = True
		return "local-storage"

	def get_content(self, encodings=None):
		if self.decode:
			return base64.b64decode(self.content.split(",")[-1])
		return self.content

	def on_trash(self):
		self.core_deleted = True


class File(file_handler.R2FileMixin, CoreFile):
	def __init__(self, **values):
		self.__dict__.update(
			is_folder=False,
			is_private=0,
			attached_to_doctype="Item",
			attached_to_name="ITEM-1",
			attached_to_field="image",
			file_name="picture.png",
			file_url="",
			content=image_bytes(),
			flags=frappe._dict(),
			decode=False,
			blob=None,
			fallback=False,
			previous=None,
		)
		self.__dict__.update(values)

	@property
	def is_remote_file(self):
		return self.file_url.startswith("https://") or not self.content

	def get(self, key, default=None):
		return self.__dict__.get(key, default)

	def check_max_file_size(self):
		return len(self._content)

	def check_content(self):
		pass

	def get_doc_before_save(self):
		return self.previous


class R2Tests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.settings = frappe._dict(SETTINGS)
		self.db = MagicMock()
		self.db.exists.return_value = False
		self.db.get_value.side_effect = lambda dt, filters, *args, **kwargs: self.db.exists(dt, filters)
		self.db.after_commit = Callbacks()
		self.db.after_rollback = Callbacks()
		self.s3 = MagicMock()
		self.s3.head_object.return_value = {"Metadata": {"managed-by": "homeall-r2", "site-id": "test"}}
		patches = [
			patch.object(frappe, "conf", frappe._dict(r2_storage=self.settings)),
			patch.object(frappe, "db", self.db),
			patch.object(
				frappe,
				"get_hooks",
				lambda key, default=None: HOOKS if key == "r2_upload_doctypes" else default,
			),
			patch.object(frappe, "get_site_path", lambda *parts: str(Path(self.temp.name, *parts))),
			patch.object(frappe, "_", lambda text: text),
			patch.object(
				frappe, "throw", side_effect=lambda msg, **kw: (_ for _ in ()).throw(ValidationFailure(msg))
			),
			patch.object(frappe, "logger", return_value=MagicMock()),
			patch.object(client, "get_client", return_value=self.s3),
			patch.object(client, "ownership", return_value={"managed-by": "homeall-r2", "site-id": "test"}),
			patch.object(storage, "object_lock", return_value=nullcontext()),
			patch.object(utils, "now_datetime", return_value=datetime(2026, 10, 21)),
		]
		for patcher in patches:
			patcher.start()
			self.addCleanup(patcher.stop)

	def test_valid_config_and_redacted_repr(self):
		self.assertEqual(config.get_config().max_bytes, 10 * 1024 * 1024)
		self.assertNotIn(self.settings.secret_access_key, repr(config.get_config()))

	def test_legacy_flat_settings_are_supported(self):
		expected = config.get_config()
		legacy = frappe._dict({f"r2_{key}": value for key, value in SETTINGS.items()})
		with patch.object(frappe, "conf", legacy):
			self.assertEqual(config.get_config(), expected)

	def test_grouped_disabled_overrides_legacy_enabled(self):
		conf = frappe._dict(r2_enabled=True, r2_storage={"enabled": False})
		with patch.object(frappe, "conf", conf):
			self.assertFalse(config.enabled())
			self.assertIsNone(config.get_config())

	def test_grouped_settings_do_not_borrow_legacy_credentials(self):
		conf = frappe._dict({f"r2_{key}": value for key, value in SETTINGS.items()})
		conf.r2_storage = {key: value for key, value in SETTINGS.items() if key != "access_key_id"}
		with patch.object(frappe, "conf", conf):
			with self.assertRaisesRegex(ValidationFailure, "r2_storage.access_key_id is required"):
				config.get_config()

	def test_invalid_grouped_configuration(self):
		for value in (None, False, [], "invalid"):
			with self.subTest(value=value), patch.object(frappe, "conf", frappe._dict(r2_storage=value)):
				with self.assertRaisesRegex(ValidationFailure, "r2_storage must be a JSON object"):
					config.get_config()

	def test_empty_grouped_configuration_disables_storage(self):
		with patch.object(frappe, "conf", frappe._dict(r2_enabled=True, r2_storage={})):
			self.assertIsNone(config.get_config())

	def test_missing_and_invalid_settings(self):
		for key, value in (
			("secret_access_key", ""),
			("account_id", "ACCOUNT_ID"),
			("public_url", "http://images.example.com"),
			("public_url", "https://user:password@example.com"),
			("key_prefix", "../other"),
			("key_prefix", "/root/"),
			("max_file_size_mb", -1),
			("max_file_size_mb", "nan"),
			("delete_on_file_delete", "false"),
			("enabled", "false"),
		):
			with self.subTest(key=key, value=value):
				self.settings.update(SETTINGS)
				self.settings[key] = value
				with self.assertRaises(ValidationFailure):
					config.get_config()

	def test_item_customer_supplier_uploads(self):
		for doctype, folder in (("Item", "items"), ("Customer", "customers"), ("Supplier", "suppliers")):
			with self.subTest(doctype=doctype):
				file = File(attached_to_doctype=doctype)
				original = file.content
				file.save_file()
				self.assertIn(f"/2026-10/{folder}/", file.file_url)
				self.assertNotIn("ITEM-1", file.file_url)
				args = self.s3.put_object.call_args.kwargs
				self.assertEqual(args["Body"], original)
				self.assertEqual(args["ContentType"], "image/png")
				self.assertNotIn("ACL", args)
				self.assertEqual(file.file_size, len(original))

	def test_multiple_attachments_and_duplicate_bytes_get_unique_keys(self):
		files = [File(attached_to_field=None) for _ in range(3)]
		for file in files:
			file.save_file()
		self.assertEqual(len({file.file_url for file in files}), 3)

	def test_default_storage_cases(self):
		for values in (
			{"attached_to_doctype": "Sales Invoice"},
			{"is_private": 1},
			{"attached_to_doctype": None, "attached_to_name": None},
			{"file_name": "document.pdf", "content": b"%PDF-1.4\nnot an image"},
		):
			with self.subTest(values=values):
				file = File(**values)
				self.assertEqual(file.save_file(), "local-storage")
		self.s3.put_object.assert_not_called()

	def test_disabled_r2_does_not_require_credentials(self):
		self.settings.enabled = False
		self.settings.secret_access_key = None
		self.assertEqual(File().save_file(), "local-storage")

	def test_invalid_image_content_and_unsupported_format(self):
		for payload in (b"not an image", image_bytes("BMP"), image_bytes()[:30]):
			with self.subTest(payload=payload[:10]), self.assertRaises(ValidationFailure):
				File(content=payload).save_file()
		self.s3.put_object.assert_not_called()

	def test_maximum_size(self):
		self.settings.max_file_size_mb = 0.00001
		with self.assertRaisesRegex(ValidationFailure, "exceeds"):
			File().save_file()
		self.s3.put_object.assert_not_called()

	def test_all_formats_and_content_based_extension(self):
		for format, (extension, mime) in utils.FORMATS.items():
			with self.subTest(format=format):
				file = File(file_name="mislabelled.txt", content=image_bytes(format))
				file.save_file()
				self.assertTrue(file.file_url.endswith("." + extension))
				self.assertEqual(self.s3.put_object.call_args.kwargs["ContentType"], mime)

	def test_jpeg_extension_preserved(self):
		file = File(file_name="photo.jpeg", content=image_bytes("JPEG"))
		file.save_file()
		self.assertTrue(file.file_url.endswith(".jpeg"))

	def test_base64_image(self):
		file = File(content=base64.b64encode(image_bytes()).decode(), decode=True)
		file.save_file()
		self.assertEqual(self.s3.put_object.call_args.kwargs["Body"], image_bytes())

	def test_network_failure_has_no_sensitive_exception_context(self):
		self.s3.put_object.side_effect = RuntimeError(self.settings.secret_access_key)
		file = File()
		try:
			file.save_file()
		except ValidationFailure as error:
			self.assertIn("R2 image upload failed", str(error))
			self.assertIsNone(error.__context__)
			self.assertNotIn(self.settings.secret_access_key, str(error))
		else:
			self.fail("Upload should fail")
		self.assertEqual(file.file_url, "")
		self.assertFalse(file.fallback)
		self.assertEqual(len(list(storage.journal_dir().glob("*.json"))), 1)

	def test_temporary_attachment_linked_later(self):
		file = File(attached_to_doctype=None, attached_to_name=None)
		file.save_file()
		self.s3.put_object.assert_not_called()
		file.attached_to_doctype, file.attached_to_name = "Item", "ITEM-1"
		file.file_url = "/files/picture.png"
		file.before_validate()
		self.assertTrue(file.file_url.startswith(SETTINGS["public_url"]))
		self.assertEqual(file.flags.r2_previous_url, "/files/picture.png")

	def test_replacement_and_delete_are_deferred_until_commit(self):
		self.settings.delete_on_file_delete = True
		old = File()
		old.save_file()
		self.db.exists.return_value = True
		self.db.after_commit.run()
		self.db.exists.return_value = False
		file = File(file_url=old.file_url, previous=old)
		file.save_file(content=image_bytes("WEBP"))
		with patch.object(file_handler, "update_references") as refs:
			file.on_update()
			refs.assert_called_once_with(file, old.file_url)
		self.assertNotEqual(file.file_url, old.file_url)
		self.s3.delete_object.assert_not_called()
		new_url = file.file_url
		self.db.exists.side_effect = lambda doctype, filters: filters.get("file_url") == new_url
		self.db.after_commit.run()
		self.s3.delete_object.assert_called_once_with(
			Bucket="test-images", Key=utils.managed_key(config.get_config(), old.file_url)
		)

	def test_delete_disabled(self):
		file = File()
		file.save_file()
		file.on_trash()
		self.assertTrue(file.core_deleted)
		self.assertEqual(len(self.db.after_commit.callbacks), 1)  # upload reconciliation only

	def test_delete_enabled_shared_and_unshared(self):
		self.settings.delete_on_file_delete = True
		url = f"{SETTINGS['public_url']}/2026-10/items/{'d' * 32}.png"
		for shared in (True, False):
			with self.subTest(shared=shared):
				self.s3.delete_object.reset_mock()
				storage.delete_after_commit(url)
				self.db.exists.return_value = shared
				self.db.after_commit.run()
				self.assertEqual(self.s3.delete_object.called, not shared)

	def test_delete_rollback_retains_object(self):
		self.settings.delete_on_file_delete = True
		storage.delete_after_commit(f"{SETTINGS['public_url']}/2026-10/items/{'d' * 32}.png")
		self.db.after_rollback.run()
		self.assertEqual(list(storage.journal_dir().glob("*.json")), [])
		self.s3.delete_object.assert_not_called()

	def test_upload_rollback_cleanup_even_when_delete_disabled(self):
		file = File()
		file.save_file()
		self.db.after_rollback.run()
		self.s3.delete_object.assert_called_once()
		self.assertEqual(list(storage.journal_dir().glob("*.json")), [])

	def test_delete_failure_is_journalled_and_retried(self):
		file = File()
		file.save_file()
		self.s3.delete_object.side_effect = TimeoutError("sensitive SDK details")
		self.db.after_rollback.run()
		paths = list(storage.journal_dir().glob("*.json"))
		self.assertEqual(len(paths), 1)
		self.s3.delete_object.side_effect = None
		storage.reconcile(paths[0])
		self.assertFalse(paths[0].exists())

	def test_unmanaged_urls_and_foreign_objects_never_deleted(self):
		self.settings.delete_on_file_delete = True
		base = SETTINGS["public_url"]
		for url in (f"{base}/important.png", f"{base}/2026-10/items/../../secret", "https://evil.test/a.png"):
			storage.delete_after_commit(url)
		self.assertEqual(len(self.db.after_commit.callbacks), 0)
		self.s3.head_object.return_value = {"Metadata": {"site-id": "another-site"}}
		storage.delete_after_commit(f"{base}/2026-10/items/{'d' * 32}.png")
		self.db.after_commit.run()
		self.s3.delete_object.assert_not_called()

	def test_prefix_boundary(self):
		self.settings.key_prefix = "staging/catalog"
		file = File()
		file.save_file()
		self.assertIn("/staging/catalog/2026-10/items/", file.file_url)
		self.assertIsNone(
			utils.managed_key(config.get_config(), file.file_url.replace("staging/catalog/", ""))
		)

	def test_rename_keeps_url_and_does_not_upload_again(self):
		file = File()
		file.save_file()
		url = file.file_url
		file.attached_to_name = "RENAMED"
		file.before_validate()
		file.on_update()
		self.assertEqual(file.file_url, url)
		self.s3.put_object.assert_called_once()

	def test_month_uses_site_clock(self):
		with patch.object(utils, "now_datetime", return_value=datetime(2026, 11, 1)):
			file = File()
			file.save_file()
		self.assertIn("/2026-11/items/", file.file_url)

	def test_local_copy_removed_only_after_commit(self):
		path = Path(self.temp.name, "public", "files", "picture.png")
		path.parent.mkdir(parents=True)
		path.write_bytes(image_bytes())
		file = File(file_url="/files/picture.png")
		file.save_file()
		self.assertTrue(path.exists())
		self.db.exists.side_effect = lambda doctype, filters: (
			doctype == "File" and filters.get("file_url") == file.file_url
		)
		self.db.after_commit.run()
		self.assertFalse(path.exists())
		self.s3.delete_object.assert_not_called()

	def test_savepoint_or_crash_recovery(self):
		File().save_file()
		with patch.object(storage.time, "time", return_value=storage.time.time() + 90000):
			storage.recover_pending()
		self.s3.delete_object.assert_called_once()

	def test_public_image_cannot_be_marked_private(self):
		file = File()
		file.save_file()
		file.is_private = 1
		with self.assertRaisesRegex(ValidationFailure, "publicly accessible"):
			file.before_validate()

	def test_boto_client_configuration(self):
		with patch("boto3.client") as factory:
			REAL_GET_CLIENT(config.get_config())
		args = factory.call_args.kwargs
		self.assertEqual(args["region_name"], "auto")
		self.assertEqual(args["endpoint_url"], f"https://{'a' * 32}.r2.cloudflarestorage.com")
		self.assertEqual(args["config"].connect_timeout, 5)
		self.assertEqual(args["config"].read_timeout, 30)
		self.assertEqual(args["config"].retries["total_max_attempts"], 3)
		self.assertEqual(args["config"].request_checksum_calculation, "when_required")

	def test_reference_lock_is_held_until_transaction_finishes(self):
		local = MagicMock(r2_reference_locks=None)
		cache = MagicMock()
		with patch.object(frappe, "local", local), patch.object(frappe, "cache", cache):
			cfg = config.get_config()
			storage.protect_reference(cfg, "key")
			storage.protect_reference(cfg, "key")
			cache.lock.return_value.acquire.assert_called_once()
			cache.lock.return_value.release.assert_not_called()
			self.db.after_commit.run()
			cache.lock.return_value.release.assert_called_once()

	def test_missing_reference_is_rejected(self):
		local = MagicMock(r2_reference_locks=None)
		self.s3.head_object.return_value = {"Metadata": {}}
		with patch.object(frappe, "local", local), patch.object(frappe, "cache", MagicMock()):
			with self.assertRaisesRegex(ValidationFailure, "missing or unavailable"):
				storage.protect_reference(config.get_config(), "key")
			self.db.after_rollback.run()

	def test_managed_file_content_read(self):
		file = File()
		file.save_file()
		self.s3.get_object.return_value = {
			"Metadata": client.ownership(),
			"Body": io.BytesIO(image_bytes()),
		}
		file.content = b""
		self.assertEqual(file.get_content(), image_bytes())

	def test_shared_local_copy_survives_commit(self):
		path = Path(self.temp.name, "public", "files", "picture.png")
		path.parent.mkdir(parents=True)
		path.write_bytes(image_bytes())
		File(file_url="/files/picture.png").save_file()
		self.db.exists.return_value = True
		self.db.after_commit.run()
		self.assertTrue(path.exists())


if __name__ == "__main__":
	unittest.main()
