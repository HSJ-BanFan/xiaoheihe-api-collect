"""Offline repository checks. This script never contacts an API or runs a signer."""
import argparse
import ast
import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist"}
BINARY_SUFFIXES = {".jar", ".apk", ".dex", ".so", ".dll", ".exe", ".p12", ".pfx", ".zip", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".whl"}
ASSET_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".pdf"}
# Assets that ship in the repository. Each digest pins the bytes the rights
# review covers, so adding or editing an asset fails offline until both this
# table and the recorded review name it.
PINNED_ASSETS = {
    "docs/assets/emoji-cry.svg":
        "d0333b5cb416ad6545055766fc8128566874ab5ead272e5a691a24704048f077",
    "docs/assets/logo.svg":
        "8a0e29cff18a957a20f01d11d3b93738e01ada093e8286b60962068fa9d3aa22",
    "docs/assets/chomper-weiqu-cover.png":
        "5bbfb77b4c2a26004879c1e1fbb76f6c6d98819f25e6027fe2a257c078a49071",
}
EXTERNAL_REFERENCE = re.compile(r"<image|<script|<use|\bhref\s*=|url\s*\(\s*['\"]?(?:https?:)?//", re.I)


def files(root):
    if (root / ".git").exists():
        result = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                capture_output=True, check=True)
        names = result.stdout.decode("utf-8").split("\x00")
        return sorted({root / name for name in names if name and (root / name).is_file()})
    return sorted(p for p in root.rglob("*") if p.is_file() and not set(p.relative_to(root).parts) & IGNORED and not any(part.endswith(".egg-info") for part in p.relative_to(root).parts))


def scan_files(root):
    errors = []
    absolute = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?:Users|home)/[A-Za-z0-9_.-]+/")
    secret = re.compile(r'''["']?(?:pkey|user_pkey|api_key|access_token|refresh_token|password)["']?\s*[:=]\s*["']([^"'\n]{16,})["']''', re.I)
    for path in files(root):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or root.resolve() not in path.resolve().parents:
            errors.append(f"symlink or external file dependency: {relative}")
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            if path.suffix.lower() not in ASSET_SUFFIXES:
                errors.append(f"binary or credential container: {relative}")
                continue
            pinned = PINNED_ASSETS.get(relative)
            raw = path.read_bytes()
            if pinned is None:
                errors.append(f"unreviewed asset: {relative} (pin it in PINNED_ASSETS and record it in the rights review)")
                continue
            if hashlib.sha256(raw).hexdigest() != pinned:
                errors.append(f"asset digest drift: {relative}")
                continue
            if path.suffix.lower() == ".svg":
                text = raw.decode("utf-8", errors="replace")
                if EXTERNAL_REFERENCE.search(text):
                    errors.append(f"asset loads external content: {relative}")
            continue
        raw = path.read_bytes()
        if b"\x00" in raw:
            errors.append(f"binary content: {relative}")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"non-UTF-8 file: {relative}")
            continue
        checked_text = text
        if relative == "cli/tests/test_login.py":
            checked_text = checked_text.replace("C:" + "/browser.exe", "INVALID_BROWSER_PATH_FIXTURE")
        if absolute.search(checked_text):
            errors.append(f"absolute host path: {relative}")
        if ("-----BEGIN " + "PRIVATE KEY-----") in text or re.search(r"gh[pousr]_[A-Za-z0-9]{30,}", text):
            errors.append(f"credential pattern: {relative}")
        if path.suffix == ".json":
            try:
                parsed = json.loads(text)
                pending = [parsed]
                while pending:
                    value = pending.pop()
                    if isinstance(value, dict):
                        if "account_alias" in value:
                            errors.append(f"private account alias field: {relative}")
                            break
                        pending.extend(value.values())
                    elif isinstance(value, list):
                        pending.extend(value)
            except ValueError:
                errors.append(f"invalid JSON: {relative}")
        for match in secret.finditer(text):
            value = match.group(1)
            synthetic_fixture = relative.startswith("cli/tests/") and value.startswith(("synthetic-", "test-only-", "stale-test-"))
            if not synthetic_fixture and not any(marker in value.lower() for marker in ("placeholder", "example", "redacted", "<", "os.environ", "getenv", "required")):
                errors.append(f"possible credential literal: {relative}")
    tracked = {path.relative_to(root).as_posix() for path in files(root)}
    for relative in sorted(set(PINNED_ASSETS) - tracked):
        errors.append(f"pinned asset is not in the repository: {relative}")
    return errors


def anchors(text):
    values = set(re.findall(r'<a\s+id="([^"]+)"', text))
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.M):
        values.add(re.sub(r"[^\w\-\s]", "", heading.lower()).strip().replace(" ", "-"))
    return values


def check_links(root):
    errors = []
    resolved_root = root.resolve()
    for path in (p for p in files(root) if p.suffix == ".md"):
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for destination in re.findall(r"\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
            url = urlsplit(destination.strip("<>"))
            if url.scheme or destination.startswith("//"):
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path.resolve()
            if target != resolved_root and resolved_root not in target.parents:
                errors.append(f"link leaves project: {path.relative_to(root)} -> {destination}")
                continue
            if not target.exists():
                errors.append(f"broken link: {path.relative_to(root)} -> {destination}")
            elif url.fragment and target.is_file() and target.suffix == ".md" and unquote(url.fragment) not in anchors(target.read_text(encoding="utf-8")):
                errors.append(f"broken anchor: {path.relative_to(root)} -> {destination}")
    return errors


def check_reference(root):
    spec = importlib.util.spec_from_file_location("reference", ROOT / "scripts" / "generate_reference.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    try:
        data = generator.load_data(root)
    except (ValueError, OSError) as exc:
        return [str(exc)]
    errors = []
    expected = generator.render(data)
    for relative, content in expected.items():
        path = root / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            errors.append(f"generated file drift: {relative}")
    for path in (root / "docs").rglob("*.md"):
        if re.fullmatch(r"[a-f0-9]{16}\.md", path.name) and path.relative_to(root).as_posix() not in expected:
            errors.append(f"orphan generated endpoint: {path.relative_to(root)}")
    catalog_path = root / "cli" / "xhh_sdk" / "api_catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for collection in ("routes", "group_routes", "review_required"):
            published = {x["path"] for x in data["interfaces"] if x["collection"] == collection}
            cli_paths = {x["route"] for x in catalog[collection]}
            if published != cli_paths:
                errors.append(f"CLI/reference path drift: {collection}")
    routes_path = root / "cli" / "xhh_sdk" / "routes.py"
    if routes_path.exists():
        tree = ast.parse(routes_path.read_text(encoding="utf-8"))
        runtime = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERIFIED_READ_ROUTES" for t in node.targets):
                runtime = set(ast.literal_eval(node.value))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "VERIFIED_READ_ROUTES":
                runtime = set(ast.literal_eval(node.value))
        expected_routes = {x["path"] for x in data["interfaces"] if x["generic_call_allowed"]}
        if runtime != expected_routes:
            errors.append("CLI runtime/reference generic allowlist drift")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = scan_files(args.root) + check_links(args.root) + check_reference(args.root)
    for error in errors:
        print(error)
    if errors:
        print(f"FAIL: {len(errors)} repository checks")
        return 1
    print("PASS: reference counts, generated files, CLI path parity, Markdown links, privacy checks, and pinned assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
