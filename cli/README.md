# xhh-sdk companion CLI

This CLI accompanies the document-led `xiaoheihe-api-collect` project. Read the
parent project's interface documentation first. The package contains an offline
catalogue and the retained Python client, not an official or complete API.

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

The build requires an installed `uv` and a cached setuptools build dependency.
An offline cache miss fails the build instead of installing from the network.
The output directory must not already exist.

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

Version `0.5.0rc4+standalone.6` keeps user-owned signer storage and lazy
signing, and adds offline APK resource preparation plus content-addressed signer bundles.
Import a user-supplied artifact with a digest you have selected explicitly:

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

Transport constructs a signer only on first signed use. Unsigned Web/COS calls
do not require JAR or Java initialization. `doctor --offline` inspects resources
and Java discovery without signing. Plain `doctor` still executes the signer.

No signer JAR, native library, account store, browser profile, or real credential
is included. Signed live requests still need a separately reviewed signer JAR.
A missing JAR produces a configuration error. Hash checking authenticates bytes,
not the JAR's publisher or safety. Java's temporary directory is not a sandbox.

The retained client supports account and live-operation commands. Their presence
does not authorize use. The standalone extraction checks were offline. The
parent project separately records a limited live acceptance for version
0.5.0rc4+standalone.6 in the [live acceptance report](../docs/research/live-acceptance.md).
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

This is a locally verified research candidate that has not been uploaded to
GitHub. The project's own code and documentation are MIT licensed; third-party
components fetched during the signer build and material that is deliberately
not distributed are described in the repository [NOTICE](../NOTICE.md). See
[release notes](RELEASE.md) for acceptance scope and verification limits.
