### Homeall Ecommerce Integration

API integration app for homeall and erpnext 

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app homeall_ecommerce_integration
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/homeall_ecommerce_integration
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit

### Cloudflare R2 public image storage

The standard File controller stores public Item, Customer, and Supplier images in R2.
JPEG, PNG, WebP, GIF, and AVIF content is decoded and validated before upload; the
integration can optimize large static images before storing them. Frappe's upload
dialog can also optimize images before they reach File. Disable both optimization
options when original bytes must be preserved.
Private files, ordinary non-image attachments, and unsupported DocTypes use normal
Frappe storage. Images with invalid content, unsupported formats, or excessive size
fail with a validation error. Eligible uploads fail if R2 is unavailable.

Merge the `r2_storage` object from [r2_site_config.example.json](r2_site_config.example.json) into
the site's existing `site_config.json`; replace every placeholder. Keep the real
configuration outside source control. No Settings DocType or frontend configuration
is needed. Required settings are validated when R2 is used. JSON booleans or 0/1
are accepted for switches; strings such as `"false"` are rejected.

All R2 settings belong inside `r2_storage`, with names such as `enabled`,
`account_id`, `public_url`, and `key_prefix` (without the old `r2_` prefix).
Other site settings remain at the top level. The reader supports legacy flat
`r2_*` settings when `r2_storage` is absent. When the object is present, it is
used exclusively, including an explicit `enabled: false`; credentials are never
mixed between grouped and legacy settings. `r2_storage` must be a JSON object.

For ecommerce uploads, `homeall.dev` enables the following optimization fields.
Keep `enabled`, credentials, and the other storage fields in this same object:

```json
{
  "r2_storage": {
    "optimize_images": true,
    "optimize_threshold_mb": 1,
    "optimize_target_kb": 300,
    "optimize_max_dimension": 1600,
    "optimize_quality": 82
  }
}
```

Validated static images at or above 1 MiB are converted to WebP, with a longest edge
of at most 1,600 pixels and initial quality 82. Smaller images retain their original
bytes. The optimizer reduces quality down to 65 (or the configured quality if lower),
then can reduce dimensions further toward a 300 KiB target, preserving aspect ratio
and avoiding enlargement. Dimension reduction stops at a 640px longest edge (or the
source size if smaller), so the byte target is best effort rather than a hard cap.
Only an encoding smaller than the source is kept. The File name, extension, MIME
type, content, and stored byte size all describe the optimized object.

Transparency and EXIF rotation are preserved; supported embedded color profiles
are converted to sRGB. EXIF/GPS/XMP metadata is removed from optimized output.
Animated GIF, WebP, PNG, and AVIF files keep their original bytes and animation.
Validation and both Frappe's upload limit and `r2_storage.max_file_size_mb` apply to the
original input before optimization. WebP encoder failures reject the eligible upload.
The encoder is part of Pillow; no additional dependency is required. Encoder details:
[Pillow WebP support](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#webp).

Optimization is opt-in when `r2_storage.optimize_images` is absent/false. Size settings must
be positive finite numbers; the maximum dimension accepts integers from 128 to 8192,
and quality accepts integers from 50 to 95. This applies to new local uploads promoted
to R2, including temporary images linked later; existing remote R2 objects are not
downloaded or rewritten. Set `r2_storage.optimize_images` to false to preserve received bytes.

Use R2 S3 credentials scoped to the configured bucket, with Object Read & Write
permission. Read is needed for File downloads, ownership checks, and cleanup.
The S3 API endpoint is derived automatically from `r2_storage.account_id`; no separate
endpoint setting is needed. `r2_storage.public_url` must be an HTTPS domain serving this bucket,
usually an R2 custom domain. An empty bucket root can return HTTP 404; verify an
individual object URL when testing the public mapping.

From the bench directory, install the dependencies and register the scheduled job:

```bash
bench setup requirements --python
bench --site YOUR_SITE migrate
bench --site YOUR_SITE clear-cache
# Restart production web and worker processes using your normal bench deployment procedure.
```

Pillow 11.3+ includes AVIF support in standard wheels; source builds need the
corresponding image codecs. The tests exercise all five image formats.

Configure DocTypes in `homeall_ecommerce_integration/hooks.py`:

```python
r2_upload_doctypes = {
    "Item": {"folder": "items"},
    "Customer": {"folder": "customers"},
    "Supplier": {"folder": "suppliers"},
}
```

Folders and `r2_storage.key_prefix` accept relative paths containing letters, digits,
underscores, hyphens, and single slashes, without leading/trailing slashes.
Keys have the form `[prefix/]YYYY-MM/folder/UUID.extension`, using the upload-time
site timezone from System Settings. Keys contain no document names. A validated
extension is preserved; mismatched extensions are replaced by the detected format.
Repeated identical uploads receive independent UUIDs, avoiding legacy cross-DocType
deduplication. Rename keeps existing object URLs unchanged.

Set `"key_prefix": "files"` inside `r2_storage` to store new uploads under
`files/YYYY-MM/folder/UUID.extension`, for example
`files/2026-10/items/a91f83c2d49b4cb891f83c2d49b4cb89.jpg`.

Attach Image fields and sidebar attachments use the same controller. Uploads without
a parent remain local. File saves and the parent `on_update` hook promote eligible
local images after linking, including Frappe's direct-SQL orphan linking. Existing
local images attached to configured documents can also be promoted when that parent
is saved. Matching Attach/Attach Image fields in the parent and its child rows are
updated together with the File URL; other records sharing the old local file keep it.
Arbitrary external image URLs are preserved and are never downloaded for migration.
Direct application SQL/database updates outside these standard lifecycles bypass
the integration; save File or its parent through the ORM after linking.

Replacement uploads always receive a new key. The old object is retained by default.
With `r2_storage.delete_on_file_delete: true`, replacement/deletion cleanup runs after commit,
checks for other File references, validates the exact managed URL/key grammar, and
checks the R2 object's app/site ownership metadata. It cannot delete arbitrary URL
paths or foreign objects. Redis locks serialize managed URL reuse with cleanup
(10-minute lease; attachment transactions must finish within that lease). Deleting a
File still follows Frappe's normal checks for references in attachment fields.
Changing an R2 File to private is rejected while the integration is enabled: a public
object cannot be made private by changing a database flag. Upload a new private file.

A private cleanup journal under `sites/YOUR_SITE/private/r2_cleanup/` records upload
intent before PUT. Full rollback cleans up unreferenced uploads even when ordinary
deletion is disabled. Successful commit removes unreferenced legacy local copies.
Failed deletion/ambiguous upload results remain journaled for retry. The hourly
`recover_pending` job reconciles intents at least 24 hours old, covering process
crashes and savepoint rollbacks, whose callbacks Frappe does not run. Referenced
objects are preserved. Keep the scheduler running and persist/share the site's
private directory across web and worker hosts. Back it up with the site; journal
records contain object identities, never credentials or image bytes.

Cleanup pauses when R2 is disabled. Changing account/bucket retains old pending
intents for operator recovery; restore that configuration to retry them. The journal
preserves an intent's upload-time prefix/public URL within the same bucket. Existing
committed images use their original URLs: do not change their public domain/prefix
without planning a migration. Ownership uses the site name and database name, so a
restored site with changed identity cannot delete the original site's objects.
Historical images retained with deletion disabled require deliberate operator cleanup.

Compatibility: `extend_doctype_class` is supported in Frappe v16+. This integration
uses the inspected File `save_file(content, decode, ignore_existing_file_check,
overwrite)` method and cooperative `super()` calls, preserving existing app hooks.
The legacy `write_file` hook is unsuitable: File and file_manager use different
signatures, and storage v2 ignores it. The installed Frappe **17.0.0-dev** checkout
was tested with both legacy and blob storage. A separate v16 release and future v17
changes still need validation on their own environments. No Frappe core files change.
The existing app's Python requirement remains `>=3.14`; installation on an older
Python runtime is outside that existing dependency constraint.
References: [Frappe extension hooks](https://docs.frappe.io/framework/user/en/python-api/hooks)
and [Cloudflare's boto3 integration](https://developers.cloudflare.com/r2/examples/aws/boto3/).

Run the offline mocked tests from the bench directory:

```bash
env/bin/python -m unittest homeall_ecommerce_integration.r2_storage.tests.test_storage homeall_ecommerce_integration.r2_storage.tests.test_image_optimizer -v
```

Run the opt-in framework checks on a development/test site with ERPNext and this app
installed. They create temporary Item/File rows and local files, use mocked R2
operations, and roll back database changes. They do not upload real R2 objects:

```bash
bench --site YOUR_SITE execute homeall_ecommerce_integration.r2_storage.tests.test_framework.run
```

The framework tests isolate site Server Scripts for Customer/Supplier and adapt the
existing sync callback's signature for the rename scenario. On `homeall.dev`, actual
Customer saving currently fails because a configured Server Script runs while Server
Scripts are disabled. Actual Item renaming also fails because the existing
`controller.update_sync_status(doc, method)` handler does not accept the extra
`old, new, merge` arguments. These pre-existing issues are outside the storage change;
the storage tests do not certify those custom flows until they are resolved.

For final deployment validation, upload a public image through an Item's image field
and its sidebar, confirm previews and URLs, then exercise Customer/Supplier images,
private images, a PDF, replacement, and deletion policy. Public-domain routing and
browser previews require an actual R2 object; mocked tests cannot verify them.
