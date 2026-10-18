from __future__ import annotations


def test_home_keyboard_has_main_sections():
    from nally.telegram.menus import home_keyboard

    keyboard = home_keyboard()
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == ["menu:chat", "menu:tools", "menu:mcp", "menu:help"]


def test_tools_screen_has_navigation():
    from nally.telegram.menus import tools_screen

    text, keyboard = tools_screen()
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "Tool directory" in text
    assert callbacks == ["menu:mcp", "menu:home"]


def test_mcp_screen_does_not_render_secret_values(monkeypatch):
    from nally.telegram import menus

    class Config:
        name = "test-server"
        enabled = True
        transport = "streamable_http"
        allowed_tools = ["list_items"]
        headers = {"Authorization": "Bearer should-never-be-rendered"}

    monkeypatch.setattr(
        "nally.tools.mcp_client.load_server_configs",
        lambda: [Config()],
        raising=False,
    )
    text, _ = menus.mcp_screen()
    assert "test-server" in text
    assert "Bearer" not in text
    assert "should-never-be-rendered" not in text
