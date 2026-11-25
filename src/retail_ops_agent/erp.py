"""The ERP client seam (ADR 0006). Agents and the pipeline reach the ERP only through ErpClient.

There are two implementations: InMemoryErp, the fake used in tests and sandboxes, and McpErpClient
(retail_ops_agent.erp_mcp), which talks to the ERP MCP server. One contract test suite runs against
both, so the fake can't drift from the server.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from copy import deepcopy
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.catalog import Catalog, SalesChannel, Sku, Supplier
from retail_ops_agent.generator import generate_opening_stock


class ErpRefusal(Exception):
    """The ERP turned a request down: an unknown code, an impossible quantity or a closed Reorder."""


class StockLevel(BaseModel):
    """Units of one SKU on hand at one Sales Channel, as the ERP records them."""

    model_config = ConfigDict(frozen=True)

    sales_channel: str
    sku: str
    on_hand: int


class ReorderStatus(StrEnum):
    PLACED = "placed"
    CANCELLED = "cancelled"


class Reorder(BaseModel):
    """A Reorder of one SKU for one Sales Channel, sent to the SKU's Supplier."""

    model_config = ConfigDict(frozen=True)

    reorder_id: str
    sales_channel: str
    sku: str
    supplier_code: str
    quantity: int
    unit_cost: float
    cost: float
    status: ReorderStatus


class ErpClient(Protocol):
    def list_sales_channels(self) -> list[SalesChannel]: ...

    def list_skus(self) -> list[Sku]: ...

    def list_suppliers(self) -> list[Supplier]: ...

    def stock_levels(self, sales_channel: str | None = None) -> list[StockLevel]:
        """Stock of every SKU, at one Sales Channel or (by default) at every Sales Channel."""
        ...

    def place_reorder(self, *, sales_channel: str, sku: str, quantity: int) -> Reorder:
        """Send a Reorder to the SKU's Supplier. Raises ErpRefusal for unknown codes or a quantity below 1."""
        ...

    def get_reorder(self, reorder_id: str) -> Reorder:
        """Raises ErpRefusal for an unknown Reorder."""
        ...

    def list_reorders(self) -> list[Reorder]:
        """Every Reorder ever placed, cancelled ones included, oldest first."""
        ...

    def cancel_reorder(self, reorder_id: str) -> Reorder:
        """Raises ErpRefusal for an unknown or already cancelled Reorder."""
        ...


class InMemoryErp:
    """An in-memory fake ERP seeded from the generator's catalog, for tests and sandboxes.

    It is also the mock ERP's state behind the ERP MCP server.
    """

    def __init__(self, catalog: Catalog, stock: Mapping[str, Mapping[str, int]] | None = None) -> None:
        """stock is units on hand by Sales Channel code, then SKU code; by default the generator's
        opening stock for the catalog. SKUs missing from it have nothing on hand."""
        if stock is None:
            stock = generate_opening_stock(catalog)
        self._catalog = catalog
        self._skus = {s.code: s for s in catalog.skus}
        self._sales_channels = {c.code for c in catalog.sales_channels}
        self._stock = {
            (channel.code, sku.code): stock.get(channel.code, {}).get(sku.code, 0)
            for channel in catalog.sales_channels
            for sku in catalog.skus
        }
        self._reorders: dict[str, Reorder] = {}
        # The ERP MCP server runs each tool call on its own worker thread, so Reorder changes are
        # serialised: otherwise two Reorders placed at once could get the same id and one be lost.
        self._reorders_lock = threading.Lock()

    def __deepcopy__(self, memo: dict[int, object]) -> InMemoryErp:
        """An independent copy of the ERP's state, with a lock of its own (a lock cannot be copied)."""
        copy = InMemoryErp.__new__(InMemoryErp)
        memo[id(self)] = copy
        with self._reorders_lock:
            for name, value in vars(self).items():
                if name != "_reorders_lock":
                    setattr(copy, name, deepcopy(value, memo))
        copy._reorders_lock = threading.Lock()
        return copy

    def list_sales_channels(self) -> list[SalesChannel]:
        return list(self._catalog.sales_channels)

    def list_skus(self) -> list[Sku]:
        return list(self._catalog.skus)

    def list_suppliers(self) -> list[Supplier]:
        return list(self._catalog.suppliers)

    def stock_levels(self, sales_channel: str | None = None) -> list[StockLevel]:
        if sales_channel is not None:
            self._check_sales_channel(sales_channel)
        return [
            StockLevel(sales_channel=channel, sku=sku, on_hand=on_hand)
            for (channel, sku), on_hand in self._stock.items()
            if sales_channel is None or channel == sales_channel
        ]

    def place_reorder(self, *, sales_channel: str, sku: str, quantity: int) -> Reorder:
        self._check_sales_channel(sales_channel)
        if sku not in self._skus:
            raise ErpRefusal(f"unknown SKU {sku!r}")
        if quantity < 1:
            raise ErpRefusal(f"a Reorder needs a quantity of at least 1, not {quantity}")
        item = self._skus[sku]
        with self._reorders_lock:
            reorder = Reorder(
                reorder_id=f"RO-{len(self._reorders) + 1:05d}",
                sales_channel=sales_channel,
                sku=sku,
                supplier_code=item.supplier_code,
                quantity=quantity,
                unit_cost=item.unit_cost,
                cost=round(quantity * item.unit_cost, 2),
                status=ReorderStatus.PLACED,
            )
            self._reorders[reorder.reorder_id] = reorder
        return reorder

    def get_reorder(self, reorder_id: str) -> Reorder:
        if reorder_id not in self._reorders:
            raise ErpRefusal(f"unknown Reorder {reorder_id!r}")
        return self._reorders[reorder_id]

    def list_reorders(self) -> list[Reorder]:
        return list(self._reorders.values())

    def cancel_reorder(self, reorder_id: str) -> Reorder:
        with self._reorders_lock:
            reorder = self.get_reorder(reorder_id)
            if reorder.status is ReorderStatus.CANCELLED:
                raise ErpRefusal(f"Reorder {reorder_id!r} is already cancelled")
            cancelled = reorder.model_copy(update={"status": ReorderStatus.CANCELLED})
            self._reorders[reorder_id] = cancelled
        return cancelled

    def _check_sales_channel(self, sales_channel: str) -> None:
        if sales_channel not in self._sales_channels:
            raise ErpRefusal(f"unknown Sales Channel {sales_channel!r}")
