"""Bounded optimization of already validated static images before R2 upload."""

import io
import math

from PIL import Image, ImageOps, features

from .config import fail


def prepare_image(image):
	image = ImageOps.exif_transpose(image)
	mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
	profile = image.info.get("icc_profile")
	if profile:
		from PIL import ImageCms

		try:
			image = ImageCms.profileToProfile(
				image,
				ImageCms.ImageCmsProfile(io.BytesIO(profile)),
				ImageCms.createProfile("sRGB"),
				outputMode=mode,
			)
		except ImageCms.PyCMSError, OSError, ValueError:
			# Invalid profiles are ignored by browsers too; use the normal mode conversion.
			image = image.convert(mode)
	else:
		image = image.convert(mode)
	# Rotation has been applied and colors converted. Drop EXIF/GPS/XMP/ICC metadata.
	image.info.clear()
	return image


def encode_webp(image, quality):
	stream = io.BytesIO()
	image.save(stream, format="WEBP", quality=quality, method=4, exact=True)
	return stream.getvalue()


def static_webp(image, config):
	image = prepare_image(image)
	image.thumbnail((config.optimize_max_dimension, config.optimize_max_dimension), Image.Resampling.LANCZOS)
	quality_floor = min(config.optimize_quality, 65)
	qualities = sorted(
		{config.optimize_quality, max(quality_floor, config.optimize_quality - 10), quality_floor},
		reverse=True,
	)
	best = None
	for quality in qualities:
		candidate = encode_webp(image, quality)
		if best is None or len(candidate) < len(best):
			best = candidate
		if len(candidate) <= config.optimize_target_bytes:
			return candidate
	# Difficult images get smaller dimensions, with a 640px longest-edge floor (or
	# their existing size if smaller). The target is best effort, not a reason to
	# reduce a product image to an unusable thumbnail. Never upscale the source.
	minimum_edge = min(640, max(image.size))
	for _ in range(4):
		if max(image.size) <= minimum_edge:
			break
		factor = min(0.85, math.sqrt(config.optimize_target_bytes / len(best)) * 0.95)
		edge = max(minimum_edge, int(max(image.size) * factor))
		image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
		candidate = encode_webp(image, quality_floor)
		if len(candidate) < len(best):
			best = candidate
		if len(candidate) <= config.optimize_target_bytes:
			break
	return best


def optimize_image(content, image_format, config):
	if not config.optimize_images or len(content) < config.optimize_threshold_bytes:
		return content, image_format
	failed = False
	try:
		with Image.open(io.BytesIO(content)) as image:
			if getattr(image, "n_frames", 1) > 1:
				return content, image_format
			if not features.check("webp"):
				raise OSError("WebP encoder unavailable")
			optimized = static_webp(image, config)
	except OSError, ValueError, ImportError:
		failed = True
	if failed:
		fail("Image optimization failed. Check the image and Pillow WebP encoder support.")
	if len(optimized) >= len(content):
		return content, image_format
	return optimized, ("webp", "image/webp")
