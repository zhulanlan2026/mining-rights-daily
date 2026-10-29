from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mining_rights_daily import __version__
from mining_rights_daily.errors import DomainError
from mining_rights_daily.prices.service import PriceQuote, Trend
from mining_rights_daily.prices.service import get_price as quote_price
from mining_rights_daily.prices.service import get_trend as quote_trend
from mining_rights_daily.servers.bootstrap import guard, serve


def build_server() -> MCPServer:
    mcp = MCPServer(
        "lme-price",
        version=__version__,
        instructions=(
            "Return a reference close and a trailing trend for lithium, copper, nickel, gold, or iron_ore. "
            "The series is bundled demonstration data. It is not an LME settlement and must not be traded on. "
            "Quote the disclaimer field in any briefing."
        ),
    )

    @mcp.tool(name="get_price")
    def get_price(commodity: str, date: str) -> PriceQuote:
        """Return the reference close for a commodity on a date.

        commodity: lithium, copper, nickel, gold, or iron_ore. Chinese aliases such as 锂 are accepted.
        date: YYYY-MM-DD, or the literal today. Weekends roll back to the previous session.
        If the date is after the series, the last session is returned and note explains the rollback.
        """

        try:
            return quote_price(commodity, date)
        except DomainError as exc:
            raise guard(exc) from exc

    @mcp.tool(name="get_trend")
    def get_trend(commodity: str, days: int) -> Trend:
        """Return the trailing reference trend.

        days: number of sessions, at least 2 and at most the length of the bundled series.
        direction is up, down, or flat using a 1 percent threshold.
        """

        try:
            return quote_trend(commodity, days)
        except DomainError as exc:
            raise guard(exc) from exc

    return mcp


def main() -> None:
    serve(build_server(), service="lme-price", default_port=8003)


if __name__ == "__main__":
    main()
