"""MCP wrapper around a session: every command is a tool, every tool call is one decision.

`tool_payload` is the part that does not need the `mcp` package: it runs one tool call through
`call_tool` (the same function the JSON Lines protocol ends in, so both drive the game the same
way) and returns the text, the optional screenshot bytes and the full answer. `serve_mcp` wires
it to an MCP server over stdio. The `mcp` package is not installed in the project environment,
so `serve_mcp` is a stub for the harness batch: written against the low-level server API of the
Python SDK and untested here. It raises a clear error if the package is missing.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

from .render import render_text
from .session import AgentSession
from .tools import call_tool, tool_schemas


def tool_payload(
    session: AgentSession, name: str, arguments: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """One tool call: `{text, image_png, answer}`. `image_png` is `None` without a screenshot."""
    answer = call_tool(session, name, arguments)
    shot = answer.get("observation", {}).get("screenshot")
    return {
        "text": render_text(answer),
        "image_png": base64.b64decode(shot["data_base64"]) if shot else None,
        "answer": answer,
    }


def serve_mcp(session: AgentSession, name: str = "noita") -> None:  # pragma: no cover - needs mcp
    """Serve the session's tools over MCP on stdio (blocks until the client disconnects)."""
    try:
        import anyio
        from mcp import types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError as err:
        raise RuntimeError(
            "serve_mcp needs the `mcp` package (pip install mcp); it is not installed here"
        ) from err

    server: Any = Server(name)

    @server.list_tools()  # type: ignore[untyped-decorator]
    async def _list_tools() -> list[Any]:
        return [types.Tool(**t) for t in tool_schemas()]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(tool: str, arguments: dict[str, Any] | None) -> list[Any]:
        result = tool_payload(session, tool, arguments)
        content: list[Any] = [types.TextContent(type="text", text=result["text"])]
        if result["image_png"] is not None:
            content.append(
                types.ImageContent(
                    type="image",
                    data=base64.b64encode(result["image_png"]).decode("ascii"),
                    mimeType="image/png",
                )
            )
        return content

    async def _run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(_run)
