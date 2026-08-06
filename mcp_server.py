"""Bob IDE MCP server.

Run over stdio (default):
    python mcp_server.py

Run as a Streamable HTTP server:
    python mcp_server.py --transport streamable-http --port 8001
"""

from __future__ import annotations

import argparse

from capabilities import CAPABILITIES

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise SystemExit(
        "The MCP SDK is not installed. Run: pip install \"mcp[cli]\""
    ) from exc


mcp = FastMCP(
    "Bob IDE",
    instructions=(
        "Operate Bob IDE workspaces through typed tools. Paths are always relative "
        "to the selected workspace. Realtime terminal, editor, filesystem, and LSP "
        "updates are delivered by the IDE Socket.IO data plane."
    ),
    json_response=True,
)

for _name, _func in CAPABILITIES.items():
    if not (_func.__doc__ or "").strip():
        _func.__doc__ = f"Bob IDE capability: {_name.replace('.', ' ').replace('_', ' ')}."
    mcp.tool(name=_name)(_func)


@mcp.resource("bob://capabilities")
def capability_catalog() -> dict:
    """List every Bob IDE tool with its human-readable description."""
    return {"tools": [{"name": name, "description": (CAPABILITIES[name].__doc__ or "").strip()} for name in sorted(CAPABILITIES)]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bob IDE MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
