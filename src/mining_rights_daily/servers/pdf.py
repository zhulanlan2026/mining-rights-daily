from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mining_rights_daily import __version__
from mining_rights_daily.errors import DomainError
from mining_rights_daily.pdfparse.document import ExtractResult
from mining_rights_daily.pdfparse.service import extract_resources as read_resources
from mining_rights_daily.servers.bootstrap import guard, serve


def build_server() -> MCPServer:
    mcp = MCPServer(
        "mineral-pdf",
        version=__version__,
        instructions=(
            "Extract NI 43-101 measured, indicated, inferred, proven, and probable rows from a text PDF. "
            "Use catalog:pilgangoora-ni43101-sample for the bundled synthetic Pilgangoora filing. "
            "That filing is a demonstration document, not a company disclosure. Scanned PDFs are rejected."
        ),
    )

    @mcp.tool(name="extract_resources")
    def extract_resources(pdf_url: str) -> ExtractResult:
        """Extract NI 43-101 resource and reserve rows from a PDF.

        pdf_url: catalog:<id>, a file URL inside the bundled reports directory, or a public http(s) PDF.
        """

        try:
            return read_resources(pdf_url)
        except DomainError as exc:
            raise guard(exc) from exc

    return mcp


def main() -> None:
    serve(build_server(), service="mineral-pdf", default_port=8002)


if __name__ == "__main__":
    main()
