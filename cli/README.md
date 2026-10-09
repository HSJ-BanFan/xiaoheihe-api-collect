# xhh-sdk companion CLI

This CLI accompanies the document-led `xiaoheihe-api-collect` project. Read the
parent project's interface documentation first. The package contains an offline
catalogue and the retained Python client, not an official or complete API.

Current candidate: `0.6.0rc1`. Web protocol support has offline tests and a
clean-wheel fixture check. Version-specific online evidence is recorded in the
[acceptance report](../docs/skill-kit-acceptance.md). A successful local build is
not a release-ready claim, and older App acceptance does not cover this candidate.

## Inspect interfaces offline

Python 3.10 or later is required. These commands need no credentials, Java, or
network access. Run them from this directory.

```powershell
python -m xhh_sdk.cli --help
python -m xhh_sdk.cli --version
python -m xhh_sdk.cli catalog --search /account/info --json
python -m xhh_sdk.cli catalog --group --json
python scripts/verify_snapshot.py
```

The catalogue preserves a reviewed historical snapshot dated 2026-10-06. Its
`live_retested` fields describe that historical evidence, not a test performed
by the current command. Relative `sources` values identify the private research
archive. They are inert strings and those files are not distributed here.
The parent project's `data/interfaces.json` is a separate documentation index.
The CLI neither reads it nor needs the parent directory at build or runtime.

## Build and verify locally

For daily use, install a built wheel normally, not with `pip install -e`.
Editable installations retain a source-directory dependency. A regular wheel
does not, but the Python environment itself still must not be moved.

The canonical build requires `uv 0.12.7` and cached `setuptools 84.0.0`.
An offline cache miss fails the build instead of installing from the network.
The output directory must not already exist.

The builder stages only allowlisted UTF-8 text with LF endings, fixes build
timestamps, and normalizes wheel member order, permissions and RECORD hashes.
Identical source produces the same wheel despite checkout timestamps or line
endings. This guarantee does not cover the source tarball. The build report
records the tool versions; a successful build is not live acceptance.

```powershell
python -m pytest tests -q
python scripts/build_release.py --out dist/local-candidate
python scripts/verify_release_install.py --release dist/local-candidate
```

The builder checks snapshot hashes, stages only named package files, and audits
the wheel and source archive. It has no publish command. The install check uses
a temporary environment, installs the wheel without dependencies or an index,
and exercises the installed CLI. It does not access a real account store.

## Runtime boundary

### Select one protocol explicitly

`protocol_mode` accepts `app` or `web`. Existing configuration and account
records without this field default to `app`. A global `--protocol` flag overrides
the selected configuration for one invocation and does not save the override.
There is no cross-protocol retry after failure.

```console
xhh-sdk --protocol web doctor --offline
xhh-sdk account configure <alias> --set protocol_mode=web --confirm
xhh-sdk --account <alias> --protocol web drafts
xhh-sdk --protocol web account status <alias> --online
```

Web uses the bundled Python signer and does not need Java, a JAR, or APK resources.
Web `doctor --offline` does not discover Java or execute signing. Web `doctor`
executes the Python signer without contacting the platform. `verify` also sends
a draft-list request; it checks draft access, not account identity. Use
`account status <alias> --online` for the identity check. Success is not promised
for a particular account or endpoint merely because the signer runs locally.

App retains the separately supplied signer described below. Protocol selection
is not permission to call arbitrary routes: `call` keeps its historical GET
allowlist, and group commands remain App-only.

### Try Creator login with your own account

Managed accounts use Windows DPAPI. The browser login flow also requires the
optional Playwright login dependency and a supported browser installed locally.
Replace `<alias>` with your own local account label.

```console
xhh-sdk account add <alias>
xhh-sdk account login <alias> --method creator --timeout 600 --confirm
xhh-sdk account status <alias> --online
xhh-sdk --account <alias> creator-options
xhh-sdk --account <alias> edit-info <link-id>
```

`creator` opens the official Creator page. Click Login and use the 小黑盒 App QR
scanner, not 微信, or the page's SMS login. The older `qr` and `browser` methods
are legacy WeChat flows; their availability is unverified. `sms` is the separate
App-session flow. Creator and legacy browser candidates are verified using Web
protocol; SMS candidates use App protocol. An explicit conflicting `--protocol`
fails before login starts.

Login checks the candidate identity before saving it. Failure leaves the prior
session unchanged. Success saves the session and its protocol together only if
the alias has not changed during the check. `creator-options` reads topic, tag,
and author-plan metadata. `edit-info` reads editable post or draft state. These
read commands do not publish anything.

### App signer compatibility

The App runtime retains user-owned signer storage, offline APK resource
preparation, and content-addressed signer bundles. Image dimensions are read
from PNG, JPEG, or GIF bytes without a third-party library.

The platform rejects an upload allocation whose file entry carries no
dimensions, so uploads no longer depend on Pillow being installed. Import a
user-supplied artifact with a digest you have selected explicitly:

```console
xhh-sdk signer install <local.jar> --sha256 <trusted-sha256> --confirm
xhh-sdk account configure <alias> --set signer_jar=managed:<sha256> --confirm
xhh-sdk signer inspect managed:<sha256>
xhh-sdk --account <alias> doctor --offline
```

The managed reference resolves under `~/.xhh_sdk/signers`, independently of
source or research directories. `XHH_SIGNER_HOME` may select an absolute store;
`--data-dir` selects account storage only. Import and inspect never execute Java.
Managed content is verified on import and before each signing invocation.
Explicit invalid paths or conflicting digest pins fail without fallback.
Legacy external paths remain location-dependent and require explicit migration.

App transport constructs a signer only on first signed use. Web sessions use
`user_pkey` and `user_heybox_id` cookies. Their upload requests include the
Creator signature; App sessions retain the older cookie-only upload protocol.
Neither upload path requires JAR or Java initialization. `doctor --offline` inspects resources
and Java discovery without signing in App mode. App `doctor` executes the signer.

Web public posts require at least one community in `topic_ids`, chosen from
`creator-options`. Hashtags do not replace a community. Missing communities
are rejected before image upload; the server checks validity and creator-plan
eligibility. A listed plan does not imply that the account may join it.

No signer JAR, native library, account store, browser profile, or real credential
is included. App-signed live requests need a separately reviewed signer JAR.
A missing JAR produces a configuration error. Hash checking authenticates bytes,
not the JAR's publisher or safety. Java's temporary directory is not a sandbox.

The retained client supports account and live-operation commands. Their presence
does not authorize use. The standalone extraction checks were offline. The
parent project separately records a limited live acceptance for version
`standalone.7` in the [historical live acceptance report](../docs/research/live-acceptance.md).
That report does not cover `0.6.0rc1` or its Web protocol.
Managed accounts use Windows DPAPI. Do not copy real profiles or credentials
into this project.

The generic `call` command accepts only the retained 243-route allowlist and
refuses payloads. It is not a generic arbitrary-endpoint runner. Other write
commands retain their confirmation gates. A historical GET success does not
prove that an endpoint remains available or has no side effects.

Private catalogue regeneration is excluded. `python -m xhh_sdk.routes --check`
checks package integrity only. `--generate` is unsupported. A future snapshot
change needs reviewed evidence and an explicit update of the pinned hashes.

## Distribution status

Release eligibility requires final-byte live acceptance and a new
hash-bound rights review. `build_release.py` reports `local_build_only` and never
marks an artifact publish-ready. The project's own code and documentation
are MIT licensed; third-party components fetched during the signer build, the
cover asset, and material that is deliberately not distributed are described in
the repository [NOTICE](../NOTICE.md). See [release notes](RELEASE.md) for
acceptance scope and verification limits.
