# Candidate and extraction notes

## Web protocol candidate

Current candidate: `0.6.0rc1`.

This candidate adds an explicit App or Web protocol, a pure Python Web signer,
per-account protocol persistence, and an invocation-only `--protocol` override.
Existing records default to App. A failed request never retries under another
protocol. Web signing does not require Java, JAR files, or APK resources.

`account login --method creator` opens the official Creator page for the user's
小黑盒 App QR scan or page SMS login. It is not the legacy WeChat QR flow. Login
verifies a candidate under its protocol before replacing the saved session, and
rejects concurrent account changes. `creator-options` exposes existing editor
metadata reads; `edit-info` reads editable post or draft state.

Offline regression tests and a disposable installed-wheel fixture check cover
the protocol dispatch and persistence. The installed check imports the Web
signer from the wheel, blocks JVM and network attempts, and substitutes HTTP
responses. It does not prove server acceptance. The intermediate build in
`dist/web-candidate-draft` is a packaging check, not the final artifact.

Fresh Creator login, upload, draft, publish, and cleanup acceptance must bind to
final candidate bytes. See the versioned parent acceptance report. The builder reports `local_build_only` with
`public_publish_ready: false`. Historical `.7` readiness does not apply to this
version. A new release requires final-byte evidence and a rights review bound to
the new distribution. Do not change the gate to reuse old success records.

## Historical runtime portability update

The historical `0.5.0rc4+standalone.7` candidate kept the `.6` work (offline
`signer prepare-apk`, `signer inspect-resources`, `signer bundle-install` and
`signer bundle-inspect`, plus a public signer loader under `signer/` that builds
and signs against a pinned public Unidbg commit) and fixes the upload allocation
request. The platform now rejects a `file_infos` entry that carries no
dimensions, and the client produced them only when Pillow happened to be
installed, so every upload on a clean install failed with `status=failed`. The
client now reads PNG, JPEG or GIF dimensions from the file bytes, and an image
whose size cannot be read fails locally with a clear error instead of reaching
the platform. The `account` help index also names both login families instead of
describing login as the WeChat QR flow only. The loader build and local signing
parity are verified: installing
a bundle and signing through the SDK reproduces the reference `hkey`/`_rnd` for
the pinned sample. SMS App login, the selected online features, the two-account
identity checks and the rights review are recorded for the candidate that the
gate clears.

On 2026-10-08, run-24 built the signer loader inside the gate and passed all 13
local steps for this wheel. Its report still listed three `not run` items and
used a schema 1 live record, so its `release_ready` field is not the final
readiness result. Run-26 reused the same wheel and loader hash with the current
schema 2, hash-bound two-account evidence. It passed all 12 local steps, its
live record and rights review validated, and it reported no open items with
`release_ready: true`, but the later pre-release audit found that its record
bound an earlier build of this wheel: two paragraphs of the package README
differed. That record therefore does not cover the shipped bytes. The release
gate now compares the wheel's embedded README against `README.md` and refuses a
stale wheel instead of reporting a live-evidence digest mismatch, and the rights
review names every shipped asset with its digest. The first acceptance run of
the `.6` build also failed at the upload allocation with `status=failed`, which
is the defect `.7` fixes; no `.6` record describes the `.7` bytes.

Readiness is decided by `scripts/release_gate.py`, not by this file. The gate
combines the local build and signing steps, a live record bound to the wheel,
loader and APK digests, and the rights review. Editing any packaged file,
including this file, changes the wheel or the source archive and needs a new
build and a new record. The parent project keeps the current report and the raw
logs, which contain workstation paths.

Live acceptance on 2026-10-08 used the test account: SMS login into an empty
store, an app-signed identity check, reads, image upload with a byte-for-byte
CDN readback, draft create/delete, and a publish/favourite/comment cycle with
verified cleanup. Both WeChat QR implementations in that historical run produced sessions the
platform rejects with `status=relogin` for app and web requests. The login
command at that version verified each returned session with an App-signed identity read and
returned nonzero when the platform rejected it. It left a rejected session in
the local account record until the user ran `account logout`. This behavior is
not retained in `0.6.0rc1`: a rejected candidate no longer replaces a saved session. A local
authenticated flag does not prove server acceptance. The risk token needs no
login: opening the site yields it. The `standalone.2` notes below
remain accurate for the runtime work they describe. Source and research folders are no longer runtime
locations for a normally installed CLI with an explicitly imported managed JAR.
Managed imports use digest-keyed user storage, inspect without Java, refuse
conflicting pins and changed bytes, and never silently replace a corrupt item.
Unsigned transport no longer constructs a signer. The separate live acceptance
executed local signing and authorized online requests for the selected flows.

The historical route observations remain unchanged. The command catalogue
includes the local signer commands and offline doctor option. The shipped
catalogue digest is pinned in `xhh_sdk/routes.py` and checked by
`python -m xhh_sdk.routes --check`; release artifact digests are listed in the
distribution's `SHA256SUMS`. The catalogue digest in the extraction history
below refers to `.1` only.

Installation verification now includes moving the distribution/resource source
away, using the installed launcher from unrelated cwd, and inspecting a managed
artifact whose original file no longer exists at its import path. Moving the
Python installation itself or moving to another Windows user is not supported.

## Historical extraction scope

The local version `0.5.0rc4+standalone.1` distinguishes the extraction from the
archived `0.5.0rc4` package. No package was published. No signer was bundled or executed.

The package retains the 18 top-level Python modules and `api_catalog.json`.
Runtime request logic and the 243-route allowlist remain unchanged. The changes
remove private route-generation tooling, add offline integrity checking, and
replace the research-dependent release procedure with an explicit file list.

The copied catalogue removes 1,734 `account_alias` fields recursively. It has no
actual parameter-value fields. Parameter names, value-provenance labels, latest
observations, historical observations, and relative evidence paths remain.
The archive's original catalogue remains unchanged.

The catalogue SHA-256 is
`5468881ecf5e4b3b24258ef48abe3bdc03d0295877e50c7e2b0be107bf440890`.
The route digest hashes the UTF-8 route strings joined with a newline and no
trailing newline. It is
`6ac5ce39ec5535cc0e386382b87e330500a3b31078ff84cd13b1abfa56d66483`.
These checks detect drift; they do not establish fresh online acceptance.

## Retained tests

The tests cover payloads, configuration, mock transports, read and write gates,
catalogue consistency, signer argument isolation, and release archive checks.
Login tests use synthetic browser and HTTP objects. Account tests use only
temporary synthetic stores; Windows-specific DPAPI checks keep their original
platform condition. No test reads the user's account database. Copied test
examples with unverified identity or phone provenance use synthetic values.

The retained test files include the following.

- `test_account_cli.py` and `test_accounts.py`.
- `test_cli_interaction.py`, `test_cli_release.py`, and `test_group_cli.py`.
- `test_interaction.py`, `test_login.py`, `test_login_qr.py`, and `test_login_sms.py`.
- `test_offline.py`, `test_catalog_data.py`, and `test_signer_release.py`.
- `test_release_package.py` and the new `test_standalone.py`.

`conftest.py` blocks real network connections and Java/browser launches during
tests. It also rejects account-store access outside the current test directory.
Subprocess CLI tests run only discovery and pre-client refusal paths.

## Deliberately excluded

The following material stays in the research archive. It was not copied and was
not replaced with skipped tests.

- `vendor`, prior `build`, `dist`, egg-info, caches, and raw examples.
- All `live_*` scripts, probing helpers, private bundle builders, and reports.
- Catalogue generators and evidence renderers that need private research files.
- `test_group_write_guard.py` and `test_live_reliability.py`, which test live
  experiment scripts rather than the extracted package.
- `test_delivery_evidence.py`, which reads private delivery reports.
- `TestGenericCall.test_snapshot_in_sync_with_case_inventory`, the catalogue
  generator check, and the static signer-audit test, which require excluded
  research tooling. New package-integrity tests replace the first two concerns.
- The three private-bundle tests and their loader in `test_release_package.py`.

The first independence run failed as intended. Route checking reported
`inventory not found; pass --results/--probe explicitly`; the build-dependency
check found `generate_catalog.py`. These were observed failures, not skipped
tests. The retained test suite and installed-wheel checks are rerunnable using
the commands in the README.

## Limits

The retained extraction tests cover offline behavior. The historical live
acceptance covers only the selected login, account, upload, creator and
interaction flows. The historical catalogue does not establish current
availability for all 448 records, complete request schemas, or write-operation
acceptance outside those flows. The build audit is a file-list and heuristic
secret check, not proof that a user-supplied signer is safe. The recorded MIT
decision covers this project's own material. See the repository NOTICE for
third-party and target-application boundaries.

Independent review corrected the CLI help and route contract to describe a
historical GET allowlist rather than promise that all entries have no side
effects. A launcher-help regression test covers that correction. Request
construction and route membership were not changed.
