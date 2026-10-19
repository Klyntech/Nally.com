"""Regression tests for authentication and tool isolation boundaries."""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

api = importlib.import_module("nally.api.app")
file_io = importlib.import_module("nally.tools.file_io")
shell = importlib.import_module("nally.tools.shell")


def test_api_auth_fails_closed_when_token_is_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(api, "ACCESS_TOKEN", "")
    monkeypatch.setattr(api, "ACCESS_TOKENS", {})

    with pytest.raises(HTTPException) as exc:
        api.require_auth("Bearer anything")

    assert exc.value.status_code == 503


@pytest.mark.parametrize("authorization", [None, "", "Basic token", "Bearer wrong"])
def test_api_auth_rejects_missing_or_invalid_tokens(monkeypatch, authorization) -> None:
    monkeypatch.setattr(api, "ACCESS_TOKEN", "configured-secret")

    with pytest.raises(HTTPException) as exc:
        api.require_auth(authorization)

    assert exc.value.status_code == 401


def test_api_auth_returns_non_secret_identity(monkeypatch) -> None:
    monkeypatch.setattr(api, "ACCESS_TOKEN", "configured-secret")

    identity = api.require_auth("Bearer configured-secret")

    assert identity
    assert identity != "configured-secret"
    assert api._api_session_id(identity, "default").startswith(f"api:{identity}:")
    assert api._api_session_id(identity, "tg:12345") != "tg:12345"


def test_api_sessions_are_namespaced_by_identity() -> None:
    first = api._api_session_id("identity-one", "default")
    second = api._api_session_id("identity-two", "default")

    assert first != second
    assert first.startswith("api:identity-one:")
    assert second.startswith("api:identity-two:")


def test_distinct_bearer_tokens_map_to_distinct_principals(monkeypatch) -> None:
    monkeypatch.setattr(api, "ACCESS_TOKEN", "")
    monkeypatch.setattr(
        api, "ACCESS_TOKENS", {"alice": "alice-secret", "bob": "bob-secret"}
    )

    alice = api.require_auth("Bearer alice-secret")
    bob = api.require_auth("Bearer bob-secret")

    assert alice != bob
    assert api._api_session_id(alice, "default") != api._api_session_id(bob, "default")


def test_telegram_webhook_fails_closed_when_secret_is_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(api, "TELEGRAM_WEBHOOK_SECRET", "")

    with pytest.raises(HTTPException) as exc:
        api._verify_telegram_webhook_secret("")

    assert exc.value.status_code == 503


@pytest.mark.parametrize("supplied", [None, "", "wrong-secret"])
def test_telegram_webhook_rejects_missing_or_invalid_secret(monkeypatch, supplied) -> None:
    monkeypatch.setattr(api, "TELEGRAM_WEBHOOK_SECRET", "telegram-secret")

    with pytest.raises(HTTPException) as exc:
        api._verify_telegram_webhook_secret(supplied)

    assert exc.value.status_code == 403


def test_telegram_webhook_accepts_exact_configured_secret(monkeypatch) -> None:
    monkeypatch.setattr(api, "TELEGRAM_WEBHOOK_SECRET", "telegram-secret")

    api._verify_telegram_webhook_secret("telegram-secret")


def test_workspace_rejects_sibling_prefix_traversal(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    sibling = tmp_path / "workspace-secret"
    workspace.mkdir()
    sibling.mkdir()
    (sibling / "secret.txt").write_text("not for Nally", encoding="utf-8")
    monkeypatch.setattr(file_io, "WORKSPACE", workspace)

    with pytest.raises(ValueError, match="escapes workspace"):
        file_io._safe("../workspace-secret/secret.txt")


def test_workspace_rejects_absolute_paths(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(file_io, "WORKSPACE", workspace)

    with pytest.raises(ValueError, match="Absolute paths"):
        file_io._safe(str(tmp_path / "secret.txt"))


def test_workspace_rejects_symlink_escape(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("private", encoding="utf-8")
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(file_io, "WORKSPACE", workspace)

    with pytest.raises(ValueError, match="escapes workspace"):
        file_io._safe("escape/secret.txt")


def test_shell_fails_closed_when_bubblewrap_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(shell, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(shell.shutil, "which", lambda _: None)

    def unexpected_run(*args, **kwargs):
        raise AssertionError("must not execute a command without isolation")

    monkeypatch.setattr(shell.subprocess, "run", unexpected_run)
    result = shell.run_command.invoke({"command": "id"})

    assert "bubblewrap is not installed" in result


def test_shell_argv_enables_namespace_isolation_and_never_mounts_host_root(tmp_path) -> None:
    argv = shell._sandbox_argv("/usr/bin/bwrap", "id", str(tmp_path))

    assert "--unshare-all" in argv
    assert "--die-with-parent" in argv
    assert "--cap-drop" in argv
    workspace_bind = next(
        argv[index : index + 3]
        for index, item in enumerate(argv)
        if item == "--bind"
    )
    assert workspace_bind == ["--bind", str(tmp_path), "/workspace"]
    assert not any(
        argv[index : index + 3] == ["--bind", "/", "/"]
        for index, item in enumerate(argv)
        if item == "--bind"
    )
