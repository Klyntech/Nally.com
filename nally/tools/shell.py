"""Run commands only inside a fail-closed bubblewrap sandbox."""
from __future__ import annotations

import os
import shutil
import subprocess

from langchain_core.tools import tool

from nally.config import CMD_TIMEOUT, MAX_TOOL_OUTPUT, WORKSPACE


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
