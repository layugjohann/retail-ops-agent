"""The ERP client that talks to the ERP MCP server (ADR 0006).

The ERP client interface is synchronous, like the Ops Day boundary, while MCP is asynchronous. So
McpErpClient keeps one MCP session open on an event loop in a background thread and waits for
each call there.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from concurrent.futures import Future
from types import TracebackType
from typing import Any, Self

from mcp import Client, StdioServerParameters
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel

from retail_ops_agent.catalog import SalesChannel, Sku, Supplier
from retail_ops_agent.erp import (
    DEFAULT_SEED,
    ErpRefusal,
    Reorder,
    ReorderList,
    SalesChannelList,
    SkuList,
    StockLevel,
    StockLevelList,
    SupplierList,
)

# How long to wait for the server to start, or for one call to return.
TIMEOUT_SECONDS = 60.0


class McpErpClient:
    """An ERP client over MCP. Use it as a context manager, or call close() when done."""

    def __init__(self, server: StdioServerParameters) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="erp-mcp-client", daemon=True)
        self._thread.start()
        self._client: Client | None = None
        self._stop: asyncio.Event | None = None
        connected: Future[None] = Future()
        self._session = asyncio.run_coroutine_threadsafe(self._hold_session(server, connected), self._loop)
        try:
            connected.result(timeout=TIMEOUT_SECONDS)
        except BaseException:
            self._shut_down_loop()
            raise

    @classmethod
    def launch(cls, seed: int = DEFAULT_SEED) -> McpErpClient:
        """Start this repository's ERP MCP server as a subprocess, seeded from the catalog, and connect."""
        return cls(
            StdioServerParameters(
                command=sys.executable, args=["-m", "retail_ops_agent.erp_server", "--seed", str(seed)]
            )
        )

    def list_sales_channels(self) -> list[SalesChannel]:
        return self._call("list_sales_channels", {}, SalesChannelList).sales_channels

    def list_skus(self) -> list[Sku]:
        return self._call("list_skus", {}, SkuList).skus

    def list_suppliers(self) -> list[Supplier]:
        return self._call("list_suppliers", {}, SupplierList).suppliers

    def stock_levels(self, sales_channel: str | None = None) -> list[StockLevel]:
        arguments = {} if sales_channel is None else {"sales_channel": sales_channel}
        return self._call("stock_levels", arguments, StockLevelList).stock_levels

    def place_reorder(self, *, sales_channel: str, sku: str, quantity: int) -> Reorder:
        arguments = {"sales_channel": sales_channel, "sku": sku, "quantity": quantity}
        return self._call("place_reorder", arguments, Reorder)

    def get_reorder(self, reorder_id: str) -> Reorder:
        return self._call("get_reorder", {"reorder_id": reorder_id}, Reorder)

    def list_reorders(self) -> list[Reorder]:
        return self._call("list_reorders", {}, ReorderList).reorders

    def cancel_reorder(self, reorder_id: str) -> Reorder:
        return self._call("cancel_reorder", {"reorder_id": reorder_id}, Reorder)

    def close(self) -> None:
        if not self._loop.is_running():
            return
        stop = self._stop
        if stop is not None:
            self._loop.call_soon_threadsafe(stop.set)
        try:
            self._session.result(timeout=TIMEOUT_SECONDS)
        finally:
            self._shut_down_loop()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    async def _hold_session(self, server: StdioServerParameters, connected: Future[None]) -> None:
        """Open the MCP session and keep it open, in one task, until close() is called."""
        self._stop = asyncio.Event()
        try:
            async with Client(server) as client:
                self._client = client
                connected.set_result(None)
                await self._stop.wait()
        except BaseException as failure:
            if not connected.done():
                connected.set_exception(failure)
            raise
        finally:
            self._client = None

    def _call[M: BaseModel](self, tool: str, arguments: dict[str, Any], output: type[M]) -> M:
        client = self._client
        if client is None:
            raise RuntimeError("the ERP MCP client is closed")
        result = asyncio.run_coroutine_threadsafe(client.call_tool(tool, arguments), self._loop).result(
            timeout=TIMEOUT_SECONDS
        )
        if result.is_error:
            raise ErpRefusal(_text(result).removeprefix(f"Error executing tool {tool}: "))
        return output.model_validate(result.structured_content)

    def _shut_down_loop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=TIMEOUT_SECONDS)
        self._loop.close()


def _text(result: CallToolResult) -> str:
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))
