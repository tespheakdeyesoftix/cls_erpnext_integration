import io
import mimetypes
import re
import warnings
from pathlib import PurePosixPath
from uuid import uuid4

import filetype
import frappe
from frappe.utils import now_datetime
from PIL import Image, UnidentifiedImageError

from .config import fail

FORMATS = {
	"JPEG": ("jpg", "image/jpeg"),
	"PNG": ("png", "image/png"),
	"WEBP": ("webp", "image/webp"),
	"GIF": ("gif", "image/gif"),
	"AVIF": ("avif", "image/avif"),
}


def image_type(content, filename, limit, supplied_mime=None):
	"""Return a validated extension/MIME, or None for ordinary non-image files."""
	kind = filetype.guess(content)
	declared = supplied_mime or mimetypes.guess_type(filename or "")[0] or ""
	claimed_image = declared.startswith("image/") or (kind and kind.mime.startswith("image/"))
	try:
		with warnings.catch_warnings():
			warnings.simplefilter("error", Image.DecompressionBombWarning)
			with Image.open(io.BytesIO(content)) as image:
				actual_format = image.format
				if actual_format not in FORMATS:
					fail("Supported R2 image formats are JPEG, PNG, WebP, GIF, and AVIF.")
				if len(content) > limit:
					fail("Image exceeds r2_storage.max_file_size_mb.")
				image.verify()
			# Some decoders' verify() is a no-op. Decode every frame to reject truncated animations.
			with Image.open(io.BytesIO(content)) as image:
				for frame in range(getattr(image, "n_frames", 1)):
					image.seek(frame)
					image.load()
	except UnidentifiedImageError:
		if claimed_image:
			fail("Invalid or unsupported image content; expected JPEG, PNG, WebP, GIF, or AVIF.")
		return None
	except OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning:
		fail("Invalid image content or unsafe image dimensions.")
	extension, mime = FORMATS[actual_format]
	original_extension = PurePosixPath(filename or "").suffix.lstrip(".").lower()
	if original_extension == extension or (actual_format == "JPEG" and original_extension in ("jpeg", "jpe")):
		extension = original_extension
	return extension, mime


def object_key(config, folder, extension):
	# now_datetime() uses System Settings.time_zone, not the server's timezone.
	parts = [config.prefix, now_datetime().strftime("%Y-%m"), folder, f"{uuid4().hex}.{extension}"]
	return "/".join(part for part in parts if part)


def managed_key(config, url):
	"""Strict URL/key grammar; ownership is additionally checked against object metadata."""
	base = config.public_url + "/"
	if not isinstance(url, str) or not url.startswith(base):
		return None
	key = url[len(base) :]
	prefix = config.prefix + "/" if config.prefix else ""
	pattern = re.escape(prefix) + (
		r"\d{4}-(?:0[1-9]|1[0-2])/(?:[A-Za-z0-9_-]+/)+[a-f0-9]{32}\.(?:jpe?g|jpe|png|webp|gif|avif)"
	)
	return key if re.fullmatch(pattern, key) else None
