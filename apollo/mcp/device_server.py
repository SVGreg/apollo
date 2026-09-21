"""Low-level device MCP server (``apollo mcp --type device``).

Thirteen raw actions — tap, long press, swipe, back, launch/stop app, open link,
text input/clear/erase, press key, screenshot, UI hierarchy — over the same
``UnifiedMobileController`` the agents use, so an IDE agent can poke a simulator
directly. The implementation lives in ``adb_server`` (its Artemis name, kept for
upstream merges); on iOS the controller drives WebDriverAgent and there is no
shell tool — host commands go through ``run_adb_command``'s ``simctl`` allowlist
in the agent server instead.
"""

from apollo.mcp.adb_server import _get_controller, configure_stdio_mode, mcp

__all__ = ["mcp", "configure_stdio_mode", "_get_controller"]

if __name__ == "__main__":
    configure_stdio_mode()
    mcp.run(transport="stdio")
