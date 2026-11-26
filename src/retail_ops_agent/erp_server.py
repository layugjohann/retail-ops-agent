"""The mock ERP as a standalone MCP server (ADR 0006), seeded from the Cobalt Home catalog.

Run it over stdio with `uv run retail-ops-erp --seed 42` (or `python -m retail_ops_agent.erp_server`).
Any MCP client can connect: McpErpClient, or a desktop client such as Claude Desktop.

The agents never get these tools. They reach the ERP through the ERP client interface, and a
Reorder is only placed after Approval or under the Auto-approval Limit.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from retail_ops_agent.erp import (
    DEFAULT_SEED,
    ErpRefusal,
    InMemoryErp,
    Reorder,
    ReorderList,
    SalesChannelList,
    SkuList,
    StockLevelList,
    SupplierList,
)
from retail_ops_agent.generator import generate_catalog

SERVER_NAME = "cobalt-home-erp"

_READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
_CANCEL = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True
)


def build_erp_server(erp: InMemoryErp) -> MCPServer:
    """An MCP server exposing the mock ERP's SKUs, stock, Suppliers and Reorders."""
    server = MCPServer(
        SERVER_NAME,
        instructions=(
            "The mock ERP of Cobalt Home, a fictional retailer. All data is simulated. Read Sales "
            "Channels, SKUs, Suppliers and stock levels; place, read and cancel Reorders."
        ),
        log_level="WARNING",
    )

    @server.tool(annotations=_READ)
    def list_sales_channels() -> SalesChannelList:
        """The Client's Sales Channels: its Stores and the Online Shop."""
        return SalesChannelList(sales_channels=erp.list_sales_channels())

    @server.tool(annotations=_READ)
    def list_skus() -> SkuList:
        """Every SKU with its category, Supplier, unit cost, retail price, case pack and lead time."""
        return SkuList(skus=erp.list_skus())

    @server.tool(annotations=_READ)
    def list_suppliers() -> SupplierList:
        """Every Supplier with its lead time in days."""
        return SupplierList(suppliers=erp.list_suppliers())

    @server.tool(annotations=_READ)
    def stock_levels(sales_channel: str | None = None) -> StockLevelList:
        """Units on hand of every SKU, at one Sales Channel (by code, e.g. ST01) or at all of them."""
        return StockLevelList(stock_levels=_refusing(lambda: erp.stock_levels(sales_channel)))

    @server.tool(annotations=_WRITE)
    def place_reorder(sales_channel: str, sku: str, quantity: int) -> Reorder:
        """Send a Reorder of a SKU for one Sales Channel to the SKU's Supplier."""
        return _refusing(lambda: erp.place_reorder(sales_channel=sales_channel, sku=sku, quantity=quantity))

    @server.tool(annotations=_READ)
    def get_reorder(reorder_id: str) -> Reorder:
        """One Reorder by its id, e.g. RO-00001."""
        return _refusing(lambda: erp.get_reorder(reorder_id))

    @server.tool(annotations=_READ)
    def list_reorders() -> ReorderList:
        """Every Reorder, cancelled ones included, oldest first."""
        return ReorderList(reorders=erp.list_reorders())

    @server.tool(annotations=_CANCEL)
    def cancel_reorder(reorder_id: str) -> Reorder:
        """Cancel a placed Reorder."""
        return _refusing(lambda: erp.cancel_reorder(reorder_id))

    return server


def _refusing[T](call: Callable[[], T]) -> T:
    """Report an ErpRefusal to the MCP client as a tool result marked as an error."""
    try:
        return call()
    except ErpRefusal as refusal:
        raise ToolError(str(refusal)) from refusal


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Cobalt Home mock ERP as an MCP server over stdio.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="generator seed for the catalog")
    args = parser.parse_args(argv)
    catalog = generate_catalog(args.seed)
    build_erp_server(InMemoryErp(catalog)).run("stdio")


if __name__ == "__main__":
    main()
