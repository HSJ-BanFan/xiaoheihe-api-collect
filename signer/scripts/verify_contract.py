"""Compile and run the pure loader boundary checks.

Only the JDK is needed. The test never loads Unidbg, a target library or the
network, and it writes solely inside the given output directory.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new local build directory")
    parser.add_argument("--resources", type=Path,
                        help="optional real prepared resources to verify as well")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "src/main/java/com/xiaoheihe/SignRequest.java",
        root / "src/main/java/com/xiaoheihe/VerifiedResources.java",
        root / "contract/ContractTest.java",
    ]
    for source in sources:
        if not source.is_file():
            raise SystemExit(f"missing loader contract source: {source}")
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        raise SystemExit("JDK 17+ is required for loader contract tests")
    out = args.out.resolve()
    if out.exists():
        raise SystemExit(f"output directory already exists: {out}")
    out.mkdir(parents=True)
    subprocess.run([javac, "--release", "17", "-encoding", "UTF-8",
                    "-d", str(out), *map(str, sources)], check=True, timeout=120)
    command = [java, "-cp", str(out), "com.xiaoheihe.ContractTest", str(out / "scratch")]
    if args.resources:
        command.append(str(args.resources.resolve()))
    subprocess.run(command, check=True, timeout=120)
    print(f"compiled classes: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
