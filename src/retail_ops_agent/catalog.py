"""The Client's catalog: Sales Channels, Suppliers and SKUs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SalesChannelKind(StrEnum):
    STORE = "store"
    ONLINE_SHOP = "online_shop"


class SalesChannel(BaseModel):
    """A Store or the Online Shop."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    kind: SalesChannelKind


class Supplier(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    lead_time_days: int


class Sku(BaseModel):
    """One sellable product variant."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    category: str
    supplier_code: str
    unit_cost: float
    retail_price: float
    case_pack: int
    lead_time_days: int


class Catalog(BaseModel):
    """Everything the Client sells, where it sells it and who supplies it."""

    model_config = ConfigDict(frozen=True)

    client_name: str
    seed: int
    sales_channels: tuple[SalesChannel, ...]
    suppliers: tuple[Supplier, ...]
    skus: tuple[Sku, ...]

    @property
    def stores(self) -> tuple[SalesChannel, ...]:
        return tuple(c for c in self.sales_channels if c.kind is SalesChannelKind.STORE)

    @property
    def online_shop(self) -> SalesChannel:
        return next(c for c in self.sales_channels if c.kind is SalesChannelKind.ONLINE_SHOP)
