"""Fail closed if an offline test attempts a real connection or JVM launch."""
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def offline_only(monkeypatch, tmp_path):
    def no_connection(*args, **kwargs):
        pytest.fail("offline test attempted a real network connection")

    monkeypatch.setattr(socket.socket, "connect", no_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", no_connection)
    for key in list(os.environ):
        if key.upper().startswith("XHH_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")

    from xhh_sdk.accounts import AccountStore
    original_init = AccountStore.__init__

    def isolated_store(self, root):
        if not Path(root).resolve().is_relative_to(tmp_path.resolve()):
            pytest.fail("account tests must use only this test's temporary directory")
        original_init(self, root)

    monkeypatch.setattr(AccountStore, "__init__", isolated_store)
    original_popen = subprocess.Popen

    def safe_child(args, *extra, **kwargs):
        executable = args[0] if isinstance(args, (list, tuple)) else args
        if Path(executable).stem.lower() in {"java", "javaw", "msedge", "chrome", "node"}:
            pytest.fail("offline test attempted to launch Java or a browser")
        return original_popen(args, *extra, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", safe_child)
