"""Inline navigation screens for the Telegram bot."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

HOME_TEXT = (
    "<b>Nally</b>  ·  Personal AI assistant\n\n"
    "Choose a section below. Chat normally at any time; the menu is just a shortcut."
)


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Chat", callback_data="menu:chat"),
            InlineKeyboardButton("🧰 Tools", callback_data="menu:tools"),
        ],
        [
            InlineKeyboardButton("🔌 MCP servers", callback_data="menu:mcp"),
            InlineKeyboardButton("❔ Help", callback_data="menu:help"),
        ],
    ])


def tools_screen() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "<b>Tool directory</b>\n\n"
        "Nally selects tools automatically during a conversation. Available capabilities "
        "depend on your deployment configuration.\n\n"
        "• <b>Memory</b> · remember and recall context\n"
        "• <b>Files</b> · list, read and write workspace files\n"
        "• <b>Web</b> · search the web and fetch pages\n"
        "• <b>Shell</b> · run configured workspace commands\n"
        "• <b>MCP</b> · connect allow-listed external tools"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔌 MCP servers", callback_data="menu:mcp")],
        [InlineKeyboardButton("← Home", callback_data="menu:home")],
    ])
    return text, keyboard


def mcp_screen() -> tuple[str, InlineKeyboardMarkup]:
    """Show safe MCP configuration metadata without revealing headers or secrets."""
    try:
        from nally.tools.mcp_client import load_server_configs
        configs = load_server_configs()
    except ImportError:
        text = (
            "<b>MCP servers</b>\n\n"
            "The MCP client manager is not available in this branch runtime yet."
        )
    except Exception:
        text = (
            "<b>MCP servers</b>\n\n"
            "MCP configuration could not be loaded. Check the server logs; sensitive "
            "configuration values are intentionally not shown here."
        )
    else:
        if not configs:
            text = (
                "<b>MCP servers</b>\n\n"
                "No MCP servers are configured. Add servers through the trusted deployment "
                "configuration; this chat menu does not edit credentials or commands."
            )
        else:
            rows = ["<b>MCP servers</b>"]
            for config in configs[:10]:
                status = "Enabled" if config.enabled else "Disabled"
                allow_count = len(config.allowed_tools)
                rows.append(
                    f"\n<b>{_escape(config.name)}</b> · {status}"
                    f"\nTransport: {_escape(config.transport)}"
                    f"\nAllow-listed tools: {allow_count}"
                )
            if len(configs) > 10:
                rows.append(f"\nShowing 10 of {len(configs)} configured servers.")
            rows.append(
                "\n\nOnly enabled servers with explicit tool allowlists can expose tools. "
                "Connection health is not inferred from configuration alone."
            )
            text = "\n".join(rows)
    return text, InlineKeyboardMarkup([
        [InlineKeyboardButton("↻ Refresh status", callback_data="menu:mcp")],
        [InlineKeyboardButton("← Home", callback_data="menu:home")],
    ])


def help_screen() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "<b>Help</b>\n\n"
        "Send a message to chat with Nally. Use the inline menu to browse capabilities "
        "and inspect MCP configuration. Buttons only navigate the interface; they do not "
        "bypass tool permissions or server-side access controls."
    )
    return text, InlineKeyboardMarkup([
        [InlineKeyboardButton("🧰 Tools", callback_data="menu:tools")],
        [InlineKeyboardButton("← Home", callback_data="menu:home")],
    ])


def _escape(value: object) -> str:
    import html
    return html.escape(str(value), quote=True)
