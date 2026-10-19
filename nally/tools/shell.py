"""Run commands only inside a fail-closed bubblewrap sandbox."""
from __future__ import annotations

import os
import shutil
import subprocess

from langchain_core.tools import tool

from nally.config import CMD_TIMEOUT, MAX_TOOL_OUTPUT, WORKSPACE

_SANDBOX_AVAILABLE: bool | None = None


def _sandbox_argv(bwrap: str, command: str, workspace: str) -> list[str]:
    """Build a network-isolated sandbox with only runtime files and workspace mounted."""
    argv = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop",
        "ALL",
    ]
    # Runtime paths are mounted read-only. Do not expose the host root, home, or repo.
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
        if os.path.exists(path):
            argv.extend(["--ro-bind", path, path])
    argv.extend(
        [
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/workspace",
            "--bind",
            workspace,
            "/workspace",
            "--chdir",
            "/workspace",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "PATH",
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "/bin/sh",
            "-lc",
            command,
        ]
    )
    return argv


@tool
def run_command(command: str) -> str:
    """Run a command in a network-isolated sandbox; fails closed without bubblewrap."""
    command = (command or "").strip()
    if not command:
        return "Error: empty command"

    bwrap = shutil.which("bwrap")
    if not bwrap:
        return "Error: isolated command execution unavailable (bubblewrap is not installed)"

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            _sandbox_argv(bwrap, command, str(WORKSPACE.resolve())),
            shell=False,
            cwd="/",
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/tmp",
                "LANG": "C.UTF-8",
            },
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if len(out) > MAX_TOOL_OUTPUT:
            out = out[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
        return f"exit={proc.returncode}\n{out}" if out else f"exit={proc.returncode}"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {CMD_TIMEOUT}s"
    except Exception as e:
        # Sandbox setup failures must not fall back to host execution.
        return f"Error: isolated command execution failed: {type(e).__name__}"



def shell_sandbox_available(*, refresh: bool = False) -> bool:
    """Probe isolation once and hide the shell tool if the sandbox cannot start."""
    global _SANDBOX_AVAILABLE
    if _SANDBOX_AVAILABLE is not None and not refresh:
        return _SANDBOX_AVAILABLE

    bwrap = shutil.which("bwrap")
    if not bwrap:
        _SANDBOX_AVAILABLE = False
        return False

    try:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        probe = subprocess.run(
            _sandbox_argv(bwrap, "true", str(WORKSPACE.resolve())),
            shell=False,
            cwd="/",
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOME": "/tmp",
                "LANG": "C.UTF-8",
            },
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        _SANDBOX_AVAILABLE = probe.returncode == 0
    except Exception:
        # A failed probe means the tool stays unavailable; never fall back to host execution.
        _SANDBOX_AVAILABLE = False
    return _SANDBOX_AVAILABLE
