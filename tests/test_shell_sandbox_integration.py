"""Integration test for real bubblewrap filesystem isolation."""
from __future__ import annotations

import importlib
import shutil

import pytest

shell = importlib.import_module("nally.tools.shell")


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap is not installed")
def test_real_sandbox_writes_workspace_and_hides_host_tmp(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    host_secret = tmp_path / "host-secret.txt"
    host_secret.write_text("host-only", encoding="utf-8")
    monkeypatch.setattr(shell, "WORKSPACE", workspace)

    workspace_result = shell.run_command.invoke(
        {"command": "printf 'sandbox-ok' > proof.txt && cat proof.txt"}
    )
    isolation_result = shell.run_command.invoke(
        {"command": f"test ! -e '{host_secret}' && echo isolated"}
    )

    assert "exit=0" in workspace_result
    assert "sandbox-ok" in workspace_result
    assert "exit=0" in isolation_result
    assert "isolated" in isolation_result
