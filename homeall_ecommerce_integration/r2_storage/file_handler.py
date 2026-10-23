"""Cooperative File mixin, using the common v16/v17 save_file seam.

The legacy write_file hook has two incompatible signatures and one has no parent
metadata. Storage v2 ignores it altogether. Intercept before core transforms/dedup
and use before_validate for legacy save_file/save_url and subsequently linked files.
"""

import io
from pathlib import PurePosixPath

import frappe
from frappe.model.document import Document
from frappe.utils import cint

from . import client, storage
from .config import doctype_folder, enabled, fail, get_config, setting
from .image_optimizer import optimize_image
from .utils import image_type, managed_key


def eligibility(doc):
	if doc.is_folder or cint(doc.is_private) or not enabled():
		return None
	if not doc.attached_to_doctype or not doc.attached_to_name:
		return None
	folder = doctype_folder(doc.attached_to_doctype)
	return (get_config(), folder) if folder else None


def attachment_rows(doc):
	yield doc
	for df in doc.meta.get_table_fields():
		yield from doc.get(df.fieldname) or []


def update_references(doc, old_url):
	"""Use metadata and equality checks; never overwrite a user's replacement field."""
	if not old_url or not doc.attached_to_doctype or not doc.attached_to_name:
		return
	if not frappe.db.exists(doc.attached_to_doctype, doc.attached_to_name):
		return
	parent = frappe.get_doc(doc.attached_to_doctype, doc.attached_to_name)
	for row in attachment_rows(parent):
		for df in row.meta.get("fields", {"fieldtype": ["in", ["Attach", "Attach Image"]]}):
			if row.get(df.fieldname) == old_url:
				row.db_set(df.fieldname, doc.file_url, update_modified=False)
				replacements = getattr(frappe.local, "r2_url_replacements", None)
				if replacements is None:
					replacements = frappe.local.r2_url_replacements = {}
				replacements[(row.doctype, row.name, df.fieldname, old_url)] = doc.file_url
				if row is parent and not doc.attached_to_field:
					doc.attached_to_field = df.fieldname
					frappe.db.set_value(
						"File", doc.name, "attached_to_field", df.fieldname, update_modified=False
					)


class R2FileMixin(Document):
	def get_content(self, encodings=None):
		if not self.get("content") and self.is_remote_file and enabled():
			config = get_config()
			if key := managed_key(config, self.file_url):
				return client.read_owned(config, key)
		return super().get_content(encodings)

	def _open_stored_bytes(self):
		if self.is_remote_file and enabled():
			config = get_config()
			if managed_key(config, self.file_url):
				return io.BytesIO(self.get_content())
		return super()._open_stored_bytes()

	def save_file(self, content=None, decode=False, ignore_existing_file_check=False, overwrite=False):
		eligible = eligibility(self)
		if not eligible:
			return super().save_file(content, decode, ignore_existing_file_check, overwrite)
		# A URL-only remote attachment is not an upload. Never fetch arbitrary URLs.
		if content is None and self.is_remote_file:
			return super().save_file(content, decode, ignore_existing_file_check, overwrite)
		if content is not None:
			self.content = content
			self.decode = decode
		payload = self.get_content()
		config, folder = eligible
		if not isinstance(payload, bytes):
			payload = payload.encode() if isinstance(payload, str) else bytes(payload)
		image_format = image_type(payload, self.file_name, config.max_bytes, self.get("content_type"))
		if not image_format:
			return super().save_file(content, decode, ignore_existing_file_check, overwrite)
		# Keep Frappe's own size/content security checks in addition to the R2 limit.
		self._content = payload
		self.check_max_file_size()  # Check the original input before any compression.
		original_payload = payload
		payload, stored_format = optimize_image(payload, image_format, config)
		file_name = self.file_name
		if payload is not original_payload:
			file_name = str(PurePosixPath(file_name).with_suffix("." + stored_format[0]))
		image_format = stored_format
		self._content = payload
		self.file_size = len(payload)
		self.file_type = image_format[0].upper()
		self.check_content()
		old_url = self.file_url
		local_url = old_url if not self.get("blob") else None
		self.file_url = storage.store(config, folder, payload, image_format, local_url)
		self.file_name = file_name
		self.content = payload
		self.decode = False
		self.content_hash = None  # R2 objects are immutable; bypass legacy disk dedup.
		self.blob = None  # v2 garbage collector owns the now-unreferenced previous blob.
		self.content_type = image_format[1]
		self.flags.r2_previous_url = old_url
		self.flags.r2_uploaded_url = self.file_url
		self.flags.r2_stored_size = len(payload)
		return {"file_name": self.file_name, "file_url": self.file_url}

	def before_save(self):
		if parent := getattr(super(), "before_save", None):
			parent()
		if self.flags.r2_uploaded_url and self.flags.r2_uploaded_url == self.file_url:
			# Core validate() may have overwritten file_size with the request's original size.
			self.file_size = self.flags.r2_stored_size

	def before_validate(self):
		if parent := getattr(super(), "before_validate", None):
			parent()
		if self.is_remote_file:
			base = setting("public_url")
			if enabled() and base and self.file_url and self.file_url.startswith(base.rstrip("/") + "/"):
				config = get_config()
				if key := managed_key(config, self.file_url):
					if cint(self.is_private):
						fail(
							"An R2 image is publicly accessible. Upload a separate private file to use private storage."
						)
					if self.flags.r2_uploaded_url != self.file_url:
						storage.protect_reference(config, key)
			return
		if not eligibility(self):
			return
		# Covers URL-only copies, temporary files linked later, and legacy file_manager.save_file.
		old_url = self.file_url
		self.save_file(content=self.get_content())
		if self.file_url != old_url:
			self.flags.r2_previous_url = old_url

	def on_update(self):
		if parent := getattr(super(), "on_update", None):
			parent()
		old_url = self.flags.pop("r2_previous_url", None)
		if old_url and old_url != self.file_url:
			update_references(self, old_url)
		previous = self.get_doc_before_save()
		if previous and previous.file_url != self.file_url and enabled():
			storage.delete_after_commit(previous.file_url)

	def on_trash(self):
		super().on_trash()
		if enabled():
			storage.delete_after_commit(self.file_url)


def sync_parent_attachments(doc, method=None):
	"""Runs after core's wildcard on_update, which may link orphans using direct SQL.

	These rows bypass File events. Save only eligible local attachments, and update
	the in-memory parent too so the Desk response contains the newly assigned URL.
	"""
	if not enabled() or not doctype_folder(doc.doctype):
		return
	for name in frappe.get_all(
		"File",
		filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "is_private": 0},
		pluck="name",
	):
		file = frappe.get_doc("File", name)
		if file.is_remote_file:
			continue
		old_url = file.file_url
		file.save(ignore_permissions=True)
		if file.file_url == old_url:
			continue
	# Core may have inserted/promoted a File before this hook and already changed its
	# parent's DB field. Refresh the response's matching in-memory fields as well.
	replacements = getattr(frappe.local, "r2_url_replacements", None) or {}
	for row in attachment_rows(doc):
		for df in row.meta.get("fields", {"fieldtype": ["in", ["Attach", "Attach Image"]]}):
			new_url = replacements.get((row.doctype, row.name, df.fieldname, row.get(df.fieldname)))
			if new_url and frappe.db.get_value(row.doctype, row.name, df.fieldname) == new_url:
				row.set(df.fieldname, new_url)
