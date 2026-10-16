"""run_command with denylist and timeout."""
from __future__ import annotations

import re
import subprocess

from langchain_core.tools import tool

from nally.config import CMD_TIMEOUT, MAX_TOOL_OUTPUT, WORKSPACE

_DENY = [
    re.compile(r"printenv", re.I),
    re.compile(r"\benv\b", re.I),
    re.compile(r"grep\s+-i\s+\S*token", re.I),
    re.compile(r"grep\s+-i\s+\S*secret", re.I),
    re.compile(r"grep\s+-i\s+\S*password", re.I),
    re.compile(r"\bexport\s+\w*KEY", re.I),
    re.compile(r"\bcat\s+.*/\.env", re.I),
    re.compile(r"\bpip\s+install", re.I),
    re.compile(r"\bnpm\s+install", re.I),
    re.compile(r"\bapt(-get)?\s+install", re.I),
    re.compile(r"\bdocker\b", re.I),
    re.compile(r"\brm\s+-rf\s+/", re.I),
]


def _denied(cmd: str) -> str | None:
    for pat in _DENY:
        if pat.search(cmd):
            return f"Command blocked by policy: matches {pat.pattern}"
    return None


@tool
def run_command(command: str) -> str:
    """Run a shell command inside the workspace sandbox. Prefer other tools when possible.
    Forbidden: env dumps, secret greps, package installs, docker, destructive root rm.
    """
    command = (command or "").strip()
    if not command:
        return "Error: empty command"
    if block := _denied(command):
        return f"Error: {block}"

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        if len(out) > MAX_TOOL_OUTPUT:
            out = out[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
        return f"exit={proc.returncode}\n{out}" if out else f"exit={proc.returncode}"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {CMD_TIMEOUT}s"
    except Exception as e:
        return f"Error: {e}"
