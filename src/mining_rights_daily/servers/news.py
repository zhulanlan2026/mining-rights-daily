from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mining_rights_daily import __version__
from mining_rights_daily.errors import DomainError
from mining_rights_daily.news.service import Article, SearchResult, search_news
from mining_rights_daily.news.service import fetch_article as read_article
from mining_rights_daily.servers.bootstrap import guard, serve


def build_server() -> MCPServer:
    mcp = MCPServer(
        "mining-news",
        version=__version__,
        instructions=(
            "Search mining news, then fetch one article by the URL returned from search. "
            "Fixture articles use fixture:// URLs and are offline samples, not wire copy. "
            "Set NEWS_ENABLE_LIVE=0 to skip mining.com RSS and ASX:PLS announcements."
        ),
    )

    @mcp.tool()
    def search(query: str, days: int = 7, as_of: str | None = None) -> SearchResult:
        """Search mining news in a trailing window.

        query: commodity, project, or region words. Chinese aliases such as 锂 and 皮尔巴拉 are accepted.
        days: inclusive window length ending on as_of. Range 1 to 800.
        as_of: optional ISO date the window ends on. Defaults to the server's current date.
        """

        try:
            return search_news(query, days, as_of)
        except DomainError as exc:
            raise guard(exc) from exc

    @mcp.tool(name="fetch_article")
    def fetch_article(url: str) -> Article:
        """Fetch one article by URL.

        Accepts fixture:// URLs from search, or a public http(s) page.
        """

        try:
            return read_article(url)
        except DomainError as exc:
            raise guard(exc) from exc

    return mcp


def main() -> None:
    serve(build_server(), service="mining-news", default_port=8001)


if __name__ == "__main__":
    main()
