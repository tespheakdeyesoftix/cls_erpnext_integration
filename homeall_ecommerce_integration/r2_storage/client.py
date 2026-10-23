import hashlib

import frappe

from .config import fail


def ownership():
	site = f"{frappe.local.site}:{frappe.conf.get('db_name')}"
	return {"managed-by": "homeall-r2", "site-id": hashlib.sha256(site.encode()).hexdigest()}


def get_client(config):
	# Lazy import keeps ordinary uploads working even before bench requirements is run.
	import boto3
	from botocore.config import Config

	return boto3.client(
		"s3",
		endpoint_url=f"https://{config.account_id}.r2.cloudflarestorage.com",
		aws_access_key_id=config.access_key_id,
		aws_secret_access_key=config.secret_access_key,
		region_name="auto",
		config=Config(
			signature_version="s3v4",
			connect_timeout=5,
			read_timeout=30,
			retries={"mode": "standard", "total_max_attempts": 3},
			request_checksum_calculation="when_required",
			response_checksum_validation="when_required",
		),
	)


def upload(config, key, content, mime):
	failed = False
	try:
		get_client(config).put_object(
			Bucket=config.bucket,
			Key=key,
			Body=content,
			ContentType=mime,
			CacheControl="public, max-age=31536000, immutable",
			Metadata=ownership(),
		)
	except Exception:
		# SDK exception text and request details can contain credentials. Never propagate them.
		failed = True
	if failed:
		fail("R2 image upload failed. Check the R2 credentials, bucket permissions, and network connection.")


def owned_object(config, key):
	from botocore.exceptions import ClientError

	try:
		result = get_client(config).head_object(Bucket=config.bucket, Key=key)
	except ClientError as error:
		if str(error.response.get("Error", {}).get("Code")) in ("404", "NoSuchKey", "NotFound"):
			return False
		raise
	return all(result.get("Metadata", {}).get(k) == v for k, v in ownership().items())


def delete_owned(config, key):
	if owned_object(config, key):
		get_client(config).delete_object(Bucket=config.bucket, Key=key)


def read_owned(config, key):
	failed = False
	try:
		result = get_client(config).get_object(Bucket=config.bucket, Key=key)
		with result["Body"] as stream:
			if not all(result.get("Metadata", {}).get(k) == v for k, v in ownership().items()):
				raise ValueError
			content = stream.read(config.max_bytes + 1)
			if len(content) > config.max_bytes:
				raise ValueError
	except Exception:
		failed = True
	if failed:
		fail("Unable to read the managed R2 image. Check the storage connection and image size limit.")
	return content
