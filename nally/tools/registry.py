from __future__ import annotations

from nally.tools.file_io import file_list, file_read, file_write
from nally.tools.library_tools import (
    library_get,
    library_list,
    library_rename,
    library_search,
)
from nally.tools.mcp_client import get_mcp_tools
from nally.tools.memory_tools import memory_forget, memory_recall, memory_remember
from nally.tools.shell import run_command
from nally.tools.web import fetch, web_search


def get_tools():
    return [
        memory_remember,
        memory_recall,
        memory_forget,
        library_list,
        library_search,
        library_get,
        library_rename,
        run_command,
        file_read,
        file_write,
        file_list,
        web_search,
        fetch,
        *get_mcp_tools(),
    ]


def get_tools_by_name():
    return {t.name: t for t in get_tools()}
