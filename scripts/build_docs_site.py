"""Stage the Markdown that the documentation site is built from.

The site needs a few repository files that live outside `docs/`, because the
documents link to them with relative paths (`../cli/README.md`,
`../../CONTRIBUTING.md`). This script copies the site sources into a staging
directory that keeps the repository layout, so every relative link resolves,
without publishing the rest of the repository.

It writes files only; it does not need MkDocs and it does not touch `docs/`.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Paths the documentation links to, relative to the repository root.
EXTRA_SOURCES = (
    "NOTICE.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "cli/README.md",
    "cli/RELEASE.md",
    "signer/README.md",
)


def prepare(stage: Path) -> dict:
    stage = stage.resolve()
    if stage == ROOT or ROOT not in stage.parents:
        raise SystemExit(f"refusing to write outside the repository: {stage}")
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(ROOT / "docs", stage / "docs")
    written = ["docs/"]
    # The theme resolves `assets/...` against the docs directory. Mirror the
    # image directory at the stage root so the same mkdocs.yml works both with
    # the staged docs directory and with the plain `docs/` directory.
    shutil.copytree(ROOT / "docs" / "assets", stage / "assets")
    written.append("assets/")
    for relative in EXTRA_SOURCES:
        source = ROOT / relative
        if not source.is_file():
            raise SystemExit(f"documentation source is missing: {relative}")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        written.append(relative)
    # The site homepage is the project README. MkDocs maps a root README.md to
    # index.html, and every link written as ../README.md resolves inside the
    # staged tree. Adding index.md as well would collide with this page.
    shutil.copy2(ROOT / "README.md", stage / "README.md")
    written += ["README.md"]
    return {"stage": str(stage), "copied": written}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, default=ROOT / "site-src")
    args = parser.parse_args(argv)
    result = prepare(args.stage)
    print(f"staged {len(result['copied'])} sources in {result['stage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
