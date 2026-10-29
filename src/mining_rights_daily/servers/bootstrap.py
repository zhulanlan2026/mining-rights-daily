from __future__ import annotations

import argparse
import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from mining_rights_daily.errors import DomainError
from mining_rights_daily.logging import configure_logging


def serve(server: MCPServer, *, service: str, default_port: int) -> None:
    configure_logging(service)
    attach_health(server, service)
    parser = argparse.ArgumentParser(description="MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", str(default_port))))
    args = parser.parse_args()
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        json_response=True,
        stateless_http=True,
    )


def attach_health(server: MCPServer, service: str) -> None:
    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse(health_payload(service))


def health_payload(service: str) -> dict[str, str]:
    return {"status": "ok", "service": service}


def guard(exc: DomainError) -> ToolError:
    return ToolError(str(exc))
