"""The ERP client seam (ADR 0006). Agents and the pipeline reach the ERP only through ErpClient."""

from __future__ import annotations

from typing import Protocol

from retail_ops_agent.catalog import Catalog, SalesChannel, Sku, Supplier


class ErpClient(Protocol):
    def list_sales_channels(self) -> list[SalesChannel]: ...

    def list_skus(self) -> list[Sku]: ...

    def list_suppliers(self) -> list[Supplier]: ...


class InMemoryErp:
    """An in-memory fake ERP seeded from the generator's catalog, for tests and sandboxes."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def list_sales_channels(self) -> list[SalesChannel]:
        return list(self._catalog.sales_channels)

    def list_skus(self) -> list[Sku]:
        return list(self._catalog.skus)

    def list_suppliers(self) -> list[Supplier]:
        return list(self._catalog.suppliers)
