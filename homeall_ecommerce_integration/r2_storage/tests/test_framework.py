"""Opt-in, rollback-only checks against the installed site's actual File controller.

Run on a development/test site with this app installed (R2 is fully mocked):
bench --site SITE execute homeall_ecommerce_integration.r2_storage.tests.test_framework.run
This creates temporary database rows and local files; all rows are rolled back.
Customer/Supplier tests isolate site Server Scripts; rename adapts the existing
sync callback's two-argument signature to Frappe's rename event arguments.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import frappe
from PIL import Image

from homeall_ecommerce_integration.r2_storage import client, storage
from homeall_ecommerce_integration.r2_storage.tests.test_storage import SETTINGS


def png():
	stream = io.BytesIO()
	Image.new("RGB", (4, 4), "blue").save(stream, format="PNG")
	return stream.getvalue()


class FrameworkTests(unittest.TestCase):
	def setUp(self):
		self.original_conf = dict(frappe.conf)
		frappe.conf.r2_storage = frappe._dict(SETTINGS)
		self.addCleanup(self.restore_config)
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.s3 = MagicMock()
		self.s3.head_object.return_value = {"Metadata": client.ownership()}
		for patcher in (
			patch.object(client, "get_client", return_value=self.s3),
			patch.object(storage, "journal_dir", return_value=Path(self.temp.name)),
		):
			patcher.start()
			self.addCleanup(patcher.stop)
		# Cleanup runs before stopping mocks, so no operation can reach Cloudflare.
		self.addCleanup(lambda: frappe.db.rollback())
		self.item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "R2-TEST-" + uuid4().hex,
				"item_name": "R2 rollback test",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"barcodes": [{"barcode": "R2-" + uuid4().hex}],
			}
		).insert(ignore_permissions=True)

	def restore_config(self):
		frappe.conf.clear()
		frappe.conf.update(self.original_conf)

	def file(self, **values):
		data = {
			"doctype": "File",
			"file_name": f"r2-{uuid4().hex}.png",
			"content": png(),
			"is_private": 0,
			"attached_to_doctype": "Item",
			"attached_to_name": self.item.name,
		}
		data.update(values)
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def test_standard_upload_field_and_multiple_attachments(self):
		main = self.file(attached_to_field="image")
		self.assertTrue(main.file_url.startswith(SETTINGS["public_url"]))
		self.item.image = main.file_url
		self.item.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Item", self.item.name, "image"), main.file_url)
		first, second = self.file(), self.file()
		self.assertNotEqual(first.file_url, second.file_url)
		self.assertEqual(frappe.db.count("File", {"attached_to_name": self.item.name}), 3)
		self.assertEqual(self.s3.put_object.call_count, 3)
		self.assertEqual(frappe.get_doc("File", main.name).file_url, main.file_url)

	def test_orphan_linked_by_parent_save(self):
		file = self.file(attached_to_doctype=None, attached_to_name=None)
		self.assertTrue(file.file_url.startswith("/files/"))
		self.s3.put_object.assert_not_called()
		self.item.image = file.file_url
		self.item.save(ignore_permissions=True)
		linked = frappe.get_doc("File", file.name)
		self.assertTrue(linked.file_url.startswith(SETTINGS["public_url"]))
		self.assertEqual(self.item.image, linked.file_url)
		self.assertEqual(frappe.db.get_value("Item", self.item.name, "image"), linked.file_url)
		self.assertEqual(linked.attached_to_name, self.item.name)
		self.s3.put_object.assert_called_once()

	def test_legacy_save_file_api(self):
		from frappe.utils.file_manager import save_file

		file = save_file("r2-legacy.png", png(), "Item", self.item.name, is_private=0, df="image")
		self.assertTrue(file.file_url.startswith(SETTINGS["public_url"]))
		self.s3.put_object.assert_called_once()

	def test_detected_image_type_overrides_filename(self):
		file = self.file(file_name="actually-an-image.pdf")
		self.assertTrue(file.file_url.endswith(".png"))
		self.assertEqual(file.file_type, "PNG")
		self.assertEqual(self.s3.put_object.call_args.kwargs["Body"], png())

	def test_large_upload_stores_optimized_size_and_format(self):
		from homeall_ecommerce_integration.r2_storage.tests.test_image_optimizer import large_png

		frappe.conf.r2_storage.optimize_images = True
		original = large_png()
		previous_size = frappe.form_dict.get("file_size")
		try:
			frappe.form_dict.file_size = len(original)
			file = self.file(content=original, file_name="large-product.png")
		finally:
			frappe.form_dict.file_size = previous_size
		body = self.s3.put_object.call_args.kwargs["Body"]
		self.assertLess(len(body), len(original))
		self.assertTrue(file.file_name.endswith(".webp"))
		self.assertTrue(file.file_url.endswith(".webp"))
		self.assertEqual(file.file_type, "WEBP")
		self.assertEqual(frappe.db.get_value("File", file.name, "file_size"), len(body))
		self.item.image = file.file_url
		self.item.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Item", self.item.name, "image"), file.file_url)

	def test_local_file_reused_by_another_parent(self):
		frappe.conf.r2_storage.enabled = False
		file = self.file()
		frappe.conf.r2_storage.enabled = True
		parent = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "R2-COPY-" + uuid4().hex,
				"item_name": "R2 copy test",
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"barcodes": [{"barcode": "R2-" + uuid4().hex}],
				"image": file.file_url,
			}
		).insert(ignore_permissions=True)
		self.assertTrue(parent.image.startswith(SETTINGS["public_url"]))
		self.assertEqual(frappe.db.get_value("Item", parent.name, "image"), parent.image)
		self.assertEqual(frappe.db.get_value("File", file.name, "file_url"), file.file_url)

	def test_actual_rollback_cleanup(self):
		file = self.file()
		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("File", file.name))
		self.s3.delete_object.assert_called_once()
		self.assertEqual(list(Path(self.temp.name).glob("*.json")), [])

	def test_upload_failure_does_not_create_file_record(self):
		self.s3.put_object.side_effect = TimeoutError("secret details")
		with self.assertRaises(frappe.ValidationError):
			self.file()
		self.assertEqual(frappe.db.count("File", {"attached_to_name": self.item.name}), 0)

	def test_customer_and_supplier_images(self):
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
		for doctype, values, folder in (
			(
				"Customer",
				{
					"customer_name": "R2-" + uuid4().hex,
					"customer_group": customer_group,
					"territory": territory,
					"customer_type": "Individual",
				},
				"customers",
			),
			(
				"Supplier",
				{
					"supplier_name": "R2-" + uuid4().hex,
					"supplier_group": "All Supplier Groups",
					"supplier_type": "Company",
				},
				"suppliers",
			),
		):
			with self.subTest(doctype=doctype):
				with patch("frappe.model.document.run_server_script_for_doc_event"):
					parent = frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)
					file = self.file(
						attached_to_doctype=doctype, attached_to_name=parent.name, attached_to_field="image"
					)
					parent.image = file.file_url
					parent.save(ignore_permissions=True)
				self.assertIn(f"/{folder}/", file.file_url)
				self.assertEqual(frappe.db.get_value(doctype, parent.name, "image"), file.file_url)

	def test_document_rename_keeps_objects(self):
		from homeall_ecommerce_integration.controller import update_sync_status

		file = self.file()
		url = file.file_url
		new_name = "R2-RENAMED-" + uuid4().hex
		with patch(
			"homeall_ecommerce_integration.controller.update_sync_status",
			side_effect=lambda doc, method, *args, **kwargs: update_sync_status(doc, method),
		):
			frappe.rename_doc("Item", self.item.name, new_name, force=True)
		file.reload()
		self.assertEqual(file.attached_to_name, new_name)
		self.assertEqual(file.file_url, url)
		self.s3.put_object.assert_called_once()

	def test_file_deletion_waits_for_commit_callback(self):
		frappe.conf.r2_storage.delete_on_file_delete = True
		file = self.file()
		# Settle the upload intent while File exists; no real DB commit is needed.
		frappe.db.after_commit.run()
		file.delete(ignore_permissions=True)
		self.s3.delete_object.assert_not_called()
		frappe.db.after_commit.run()
		self.s3.delete_object.assert_called_once()

	def test_replacement_updates_standard_item_field(self):
		file = self.file(attached_to_field="image")
		self.item.image = file.file_url
		self.item.save(ignore_permissions=True)
		old_url = file.file_url
		file.save_file(content=png(), overwrite=True)
		file.save(ignore_permissions=True)
		self.assertNotEqual(file.file_url, old_url)
		self.assertEqual(frappe.db.get_value("Item", self.item.name, "image"), file.file_url)
		self.s3.delete_object.assert_not_called()

	def test_private_and_pdf_stay_local(self):
		from pypdf import PdfWriter

		private = self.file(is_private=1)
		self.assertTrue(private.file_url.startswith("/private/files/"))
		stream = io.BytesIO()
		writer = PdfWriter()
		writer.add_blank_page(width=72, height=72)
		writer.write(stream)
		pdf = self.file(file_name="r2-document.pdf", content=stream.getvalue())
		self.assertTrue(pdf.file_url.startswith("/files/"))
		self.s3.put_object.assert_not_called()


def run():
	result = unittest.TextTestRunner(verbosity=2).run(
		unittest.defaultTestLoader.loadTestsFromTestCase(FrameworkTests)
	)
	if not result.wasSuccessful():
		raise AssertionError("R2 framework tests failed")
	return {"tests": result.testsRun, "passed": True}
