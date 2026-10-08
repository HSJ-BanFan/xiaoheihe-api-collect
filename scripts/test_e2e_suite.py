"""Full automated end-to-end self-test suite for xhh-sdk.

Run:
    python scripts/test_e2e_suite.py [--account ALIAS]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def run() -> int:
    parser = argparse.ArgumentParser(description="Run full end-to-end tests across accounts")
    parser.add_argument("--account", default=None, help="Account alias to test (default: all logged-in)")
    args = parser.parse_args()

    exe_path = shutil.which("xhh-sdk") or os.path.expanduser("~/.creator-workbench/venv/Scripts/xhh-sdk.exe")
    if not os.path.exists(exe_path):
        print(f"Error: xhh-sdk launcher not found at {exe_path}")
        return 1

    p_acc = subprocess.run([exe_path, "account", "list"], capture_output=True, check=False)
    data = json.loads(p_acc.stdout.decode("utf-8", errors="replace"))
    accounts = [a["alias"] for a in data.get("accounts", []) if a.get("authenticated")]

    target_accounts = [args.account] if args.account else accounts
    if not target_accounts:
        print("No authenticated accounts found.")
        return 1

    print(f"Found active accounts: {target_accounts}")
    overall_ok = True

    for account in target_accounts:
        print("\n==================================================")
        print(f"  Running Full E2E Test on Account: [{account}]")
        print("==================================================")
        tests = []

        # 1. account status --online
        t0 = time.time()
        p = subprocess.run([exe_path, "account", "status", account, "--online"], capture_output=True, check=False)
        tests.append(("1. Account Online Status (API identity check)", p.returncode == 0, round(time.time() - t0, 2)))

        # 2. doctor --offline
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "doctor", "--offline"], capture_output=True, check=False)
        tests.append(("2. Doctor Offline (No-Java path check)", p.returncode == 0, round(time.time() - t0, 2)))

        # 3. doctor online
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "doctor"], capture_output=True, check=False)
        tests.append(("3. Doctor Online (Signer Java runtime & SO check)", p.returncode == 0, round(time.time() - t0, 2)))

        # 4. verify
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "verify"], capture_output=True, check=False)
        tests.append(("4. Verify Smoke (Signer & Drafts list roundtrip)", p.returncode == 0, round(time.time() - t0, 2)))

        # 5. drafts
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "drafts"], capture_output=True, check=False)
        tests.append(("5. Business Read: Drafts list", p.returncode == 0, round(time.time() - t0, 2)))

        # 6. posts
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "posts"], capture_output=True, check=False)
        tests.append(("6. Business Read: Own Posts list", p.returncode == 0, round(time.time() - t0, 2)))

        # 7. my-comments
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "my-comments"], capture_output=True, check=False)
        tests.append(("7. Business Read: Comments list", p.returncode == 0, round(time.time() - t0, 2)))

        # 8. call search/topic
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "call", "/bbs/app/api/search/topic", "--query", "q=Steam"], capture_output=True, check=False)
        tests.append(("8. Allowlist Call: /bbs/app/api/search/topic", p.returncode == 0, round(time.time() - t0, 2)))

        # 9. call hashtag/search
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "call", "/bbs/app/hashtag/search", "--query", "q=黑神话"], capture_output=True, check=False)
        tests.append(("9. Allowlist Call: /bbs/app/hashtag/search", p.returncode == 0, round(time.time() - t0, 2)))

        # 10. call account/info
        t0 = time.time()
        p = subprocess.run([exe_path, "--account", account, "call", "/account/info"], capture_output=True, check=False)
        tests.append(("10. Allowlist Call: /account/info", p.returncode == 0, round(time.time() - t0, 2)))

        # 11. upload (Tencent COS)
        t0 = time.time()
        img_path = os.path.join(os.path.dirname(__file__), "test_sample.png")
        with open(img_path, "wb") as fp:
            fp.write(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f00050001ff9d6f6b1a0000000049454e44ae426082"))
        p = subprocess.run([exe_path, "--account", account, "upload", img_path, "--confirm"], capture_output=True, check=False)
        img_url = ""
        if p.returncode == 0:
            try:
                img_url = json.loads(p.stdout.decode("utf-8"))[0].get("url", "")
            except Exception:
                pass
        tests.append(("11. Web COS Upload: Image upload to CDN", p.returncode == 0 and bool(img_url), round(time.time() - t0, 2)))

        # 12. publish draft -> readback -> delete lifecycle (Reversible Write with Zero Residuals)
        t0 = time.time()
        spec = json.dumps({
            "title": "E2E-AUTO-PIPELINE",
            "content": "<p>Automated regression test draft</p>",
            "images": [img_url] if img_url else [],
            "draft": True
        })
        p_create = subprocess.run([exe_path, "--account", account, "publish", "-", "--confirm"], input=spec.encode("utf-8"), capture_output=True, check=False)
        link_id = ""
        if p_create.returncode == 0:
            try:
                link_id = str(json.loads(p_create.stdout.decode("utf-8")).get("link_id") or "")
            except Exception:
                pass

        del_ok = False
        if link_id:
            p_del = subprocess.run([exe_path, "--account", account, "delete", link_id, "--confirm"], capture_output=True, check=False)
            del_ok = (p_del.returncode == 0)

        lifecycle_ok = bool(link_id) and del_ok
        tests.append(("12. Reversible Lifecycle: Create draft -> Delete", lifecycle_ok, round(time.time() - t0, 2)))

        if os.path.exists(img_path):
            try:
                os.remove(img_path)
            except Exception:
                pass

        for name, ok, cost in tests:
            status = "PASS" if ok else "FAIL"
            print(f"  [{status:4}] {name:50} ({cost}s)")

        acc_ok = sum(1 for _, ok, _ in tests if ok)
        print(f"\n--> Result for [{account}]: {acc_ok}/{len(tests)} Passed")
        if acc_ok != len(tests):
            overall_ok = False

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(run())
