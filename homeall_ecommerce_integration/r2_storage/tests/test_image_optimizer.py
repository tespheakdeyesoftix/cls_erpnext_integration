import io
import random
import unittest
from dataclasses import replace
from functools import lru_cache
from unittest.mock import patch

from PIL import Image, ImageCms

from homeall_ecommerce_integration.r2_storage import config, file_handler, image_optimizer
from homeall_ecommerce_integration.r2_storage.tests import test_storage as storage_tests


@lru_cache(maxsize=2)
def large_png(alpha=False):
	mode = "RGBA" if alpha else "RGB"
	image = Image.frombytes("RGB", (1800, 1200), random.Random(42).randbytes(1800 * 1200 * 3))
	if alpha:
		image = image.convert(mode)
		image.putalpha(128)
	stream = io.BytesIO()
	image.save(stream, format="PNG")
	return stream.getvalue()


class OptimizerTests(unittest.TestCase):
	def setUp(self):
		storage_tests.R2Tests.setUp(self)
		self.settings.optimize_images = True

	def optimize(self, content, image_format=("png", "image/png")):
		return image_optimizer.optimize_image(content, image_format, config.get_config())

	def test_large_image_becomes_smaller_webp(self):
		original = large_png()
		self.assertGreater(len(original), 1024 * 1024)
		content, kind = self.optimize(original)
		self.assertEqual(kind, ("webp", "image/webp"))
		self.assertLess(len(content), len(original))
		self.assertLessEqual(len(content), 300 * 1024)
		with Image.open(io.BytesIO(content)) as image:
			self.assertLessEqual(max(image.size), 1600)
			self.assertAlmostEqual(image.width / image.height, 1.5, places=2)

	def test_small_image_bytes_are_preserved(self):
		original = storage_tests.image_bytes()
		content, kind = self.optimize(original)
		self.assertIs(content, original)
		self.assertEqual(kind, ("png", "image/png"))

	def test_optimization_disabled_preserves_large_image(self):
		self.settings.optimize_images = False
		content, kind = self.optimize(large_png())
		self.assertIs(content, large_png())
		self.assertEqual(kind, ("png", "image/png"))

	def test_threshold_is_inclusive(self):
		original = storage_tests.image_bytes()
		settings = replace(config.get_config(), optimize_threshold_bytes=len(original))
		with patch.object(image_optimizer, "static_webp", return_value=b"encoded") as encode:
			image_optimizer.optimize_image(original, ("png", "image/png"), settings)
			encode.assert_called_once()
			encode.reset_mock()
			settings = replace(settings, optimize_threshold_bytes=len(original) + 1)
			self.assertEqual(
				image_optimizer.optimize_image(original, ("png", "image/png"), settings)[0], original
			)
			encode.assert_not_called()

	def test_transparent_images_keep_alpha(self):
		content, _ = self.optimize(large_png(alpha=True))
		with Image.open(io.BytesIO(content)) as image:
			self.assertEqual(image.mode, "RGBA")
			self.assertEqual(image.getchannel("A").getextrema(), (128, 128))

	def test_rotation_is_applied_and_metadata_removed_without_upscaling(self):
		self.settings.optimize_threshold_mb = 1 / 1048576
		image = Image.new("RGB", (300, 160), "blue")
		exif = Image.Exif()
		exif[274] = 6
		exif[271] = "Test camera"
		stream = io.BytesIO()
		image.save(stream, format="JPEG", exif=exif)
		content, kind = self.optimize(stream.getvalue(), ("jpg", "image/jpeg"))
		self.assertEqual(kind, ("webp", "image/webp"))
		with Image.open(io.BytesIO(content)) as image:
			self.assertEqual(image.size, (160, 300))
			self.assertFalse(image.getexif())

	def test_supported_icc_profile_is_converted_to_srgb(self):
		self.settings.optimize_threshold_mb = 1 / 1048576
		image = Image.new("RGB", (100, 100), (120, 80, 40))
		profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
		stream = io.BytesIO()
		image.save(stream, format="PNG", icc_profile=profile)
		content, _ = self.optimize(stream.getvalue())
		with Image.open(io.BytesIO(content)) as image:
			self.assertNotIn("icc_profile", image.info)
			for actual, expected in zip(image.getpixel((50, 50)), (120, 80, 40), strict=True):
				self.assertLess(abs(actual - expected), 10)

	def test_animations_are_preserved(self):
		self.settings.optimize_threshold_mb = 1 / 1048576
		for format, kind in (
			("GIF", ("gif", "image/gif")),
			("WEBP", ("webp", "image/webp")),
			("PNG", ("png", "image/png")),
		):
			with self.subTest(format=format):
				stream = io.BytesIO()
				Image.new("RGB", (20, 20), "red").save(
					stream,
					format=format,
					save_all=True,
					append_images=[Image.new("RGB", (20, 20), "blue")],
					duration=100,
					loop=0,
				)
				original = stream.getvalue()
				content, result_kind = self.optimize(original, kind)
				self.assertIs(content, original)
				self.assertEqual(result_kind, kind)
				with Image.open(io.BytesIO(content)) as image:
					self.assertEqual(image.n_frames, 2)

	def test_larger_encoding_is_discarded(self):
		self.settings.optimize_threshold_mb = 1 / 1048576
		original = storage_tests.image_bytes()
		with patch.object(image_optimizer, "encode_webp", return_value=b"x" * (len(original) + 1)):
			content, kind = self.optimize(original)
		self.assertIs(content, original)
		self.assertEqual(kind, ("png", "image/png"))

	def test_encoder_failure_stops_upload(self):
		file = storage_tests.File(content=large_png())
		with patch.object(image_optimizer, "encode_webp", side_effect=OSError("bad encoder")):
			with self.assertRaisesRegex(storage_tests.ValidationFailure, "optimization failed"):
				file.save_file()
		self.s3.put_object.assert_not_called()
		self.assertEqual(file.file_url, "")

	def test_upload_metadata_matches_stored_bytes(self):
		file = storage_tests.File(content=large_png(), file_name="product.png")
		file.save_file()
		body = self.s3.put_object.call_args.kwargs["Body"]
		self.assertEqual(self.s3.put_object.call_args.kwargs["ContentType"], "image/webp")
		self.assertTrue(file.file_url.endswith(".webp"))
		self.assertEqual(file.file_name, "product.webp")
		self.assertEqual(file.file_type, "WEBP")
		self.assertEqual(file.file_size, len(body))
		self.assertEqual(file.get_content(), body)
		file.file_size = len(large_png())  # Simulate core's request-size override.
		file.before_save()
		self.assertEqual(file.file_size, len(body))

	def test_input_size_limit_applies_before_optimization(self):
		self.settings.max_file_size_mb = 1
		with patch.object(file_handler, "optimize_image") as optimize:
			with self.assertRaisesRegex(storage_tests.ValidationFailure, "exceeds"):
				storage_tests.File(content=large_png()).save_file()
			optimize.assert_not_called()
		self.s3.put_object.assert_not_called()

	def test_other_storage_paths_do_not_optimize(self):
		with patch.object(file_handler, "optimize_image") as optimize:
			for values in (
				{"is_private": 1},
				{"attached_to_doctype": "Sales Invoice"},
				{"file_name": "invoice.pdf", "content": b"%PDF-1.4\nnot an image"},
			):
				self.assertEqual(storage_tests.File(**values).save_file(), "local-storage")
			optimize.assert_not_called()

	def test_custom_max_dimension(self):
		self.settings.optimize_max_dimension = 256
		content, kind = self.optimize(large_png())
		self.assertEqual(kind, ("webp", "image/webp"))
		with Image.open(io.BytesIO(content)) as image:
			self.assertLessEqual(max(image.size), 256)

	def test_invalid_optimization_configuration(self):
		for key, value in (
			("optimize_images", "true"),
			("optimize_threshold_mb", 0),
			("optimize_threshold_mb", "nan"),
			("optimize_target_kb", -1),
			("optimize_max_dimension", 127),
			("optimize_max_dimension", 8193),
			("optimize_max_dimension", 1600.5),
			("optimize_quality", 96),
			("optimize_quality", True),
		):
			with self.subTest(key=key, value=value):
				self.settings.update(storage_tests.SETTINGS)
				self.settings.optimize_images = True
				self.settings[key] = value
				with self.assertRaises(storage_tests.ValidationFailure):
					config.get_config()
				self.settings.pop(key, None)


if __name__ == "__main__":
	unittest.main()
