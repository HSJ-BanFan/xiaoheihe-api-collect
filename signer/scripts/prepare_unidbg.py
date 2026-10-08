"""Build the pinned public unidbg commit into a private local repository.

The published `unidbg-android:0.9.9` artifact faults inside the pinned target
library, so this module builds against a local build of the public upstream
commit below (Apache-2.0). On JDK 9+ three files also need an explicit
`com.github.unidbg.Module` import, because the bare `Module` reference clashes
with `java.lang.Module`.

Usage:
    python scripts/prepare_unidbg.py --work <checkout-dir> --repo <maven-repo>

Then build this module with `-Dmaven.repo.local=<maven-repo>` (or add that
repository to your Maven settings).
"""
import argparse
from pathlib import Path
import subprocess
import sys

COMMIT = "2ded0545d4ae053055f469ef4a4c49e3f15196a7"
CLONE_URL = "https://github.com/zhkl0228/unidbg.git"
IMPORT = "import com.github.unidbg.Module;"
PATCH_TARGETS = (
    "unidbg-api/src/main/java/com/github/unidbg/arm/AbstractARMDebugger.java",
    "unidbg-android/src/main/java/com/github/unidbg/linux/AndroidElfLoader.java",
    "unidbg-ios/src/main/java/com/github/unidbg/ios/MachOLoader.java",
)


def run(args, cwd=None):
    print("+", " ".join(str(part) for part in args))
    subprocess.run([str(part) for part in args], cwd=cwd, check=True)


def checkout(work: Path, clone_url: str) -> None:
    if (work / ".git").is_dir():
        run(["git", "-C", work, "fetch", "--depth", "1", "origin", COMMIT])
        run(["git", "-C", work, "checkout", "--force", "FETCH_HEAD"])
        return
    work.mkdir(parents=True, exist_ok=True)
    run(["git", "init", work])
    run(["git", "-C", work, "remote", "add", "origin", clone_url])
    try:
        run(["git", "-C", work, "fetch", "--depth", "1", "origin", COMMIT])
        run(["git", "-C", work, "checkout", "--force", "FETCH_HEAD"])
    except subprocess.CalledProcessError:
        print("shallow fetch by commit failed; falling back to a full clone")
        run(["git", "-C", work, "fetch", "origin"])
        run(["git", "-C", work, "checkout", "--force", COMMIT])


def patch(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if IMPORT in text:
        return "already patched"
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    if len(lines) < 3 or not lines[0].startswith("package "):
        raise SystemExit(f"unexpected file shape: {path}")
    lines.insert(2, IMPORT + newline)
    lines.insert(3, newline)
    path.write_text("".join(lines), encoding="utf-8", newline="")
    return "patched"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True, help="checkout directory")
    parser.add_argument("--repo", type=Path, required=True, help="private Maven repository")
    parser.add_argument("--clone-url", default=CLONE_URL)
    parser.add_argument("--maven", default="mvn", help="mvn executable")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args(argv)
    work = args.work.resolve()
    repo = args.repo.resolve()
    checkout(work, args.clone_url)
    for relative in PATCH_TARGETS:
        path = work / relative
        if not path.is_file():
            raise SystemExit(f"missing source file: {path}")
        print(f"{patch(path)}: {relative}")
    if args.skip_build:
        print("sources ready; build skipped")
        return 0
    repo.mkdir(parents=True, exist_ok=True)
    run([args.maven, "-B", "-DskipTests", "-Dgpg.skip=true",
         f"-Dmaven.repo.local={repo}", "-f", work / "pom.xml", "install"])
    print(f"installed unidbg {COMMIT} into {repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
