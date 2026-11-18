"""The ERP contract: one suite, run through the ERP client interface against both the in-memory fake
ERP and the ERP MCP server, so the fake can't drift from the server."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from retail_ops_agent.catalog import Catalog
from retail_ops_agent.erp import ErpClient, ErpRefusal, InMemoryErp, ReorderStatus
from retail_ops_agent.erp_mcp import McpErpClient
from retail_ops_agent.generator import generate_opening_stock
from tests.conftest import SEED


@pytest.fixture(params=["in_memory_fake", "mcp_server"])
def erp(request: pytest.FixtureRequest, catalog: Catalog) -> Iterator[ErpClient]:
    if request.param == "in_memory_fake":
        yield InMemoryErp(catalog)
    else:
        with McpErpClient.launch(SEED) as client:
            yield client


def test_reads_the_catalog_sales_channels_skus_and_suppliers(erp: ErpClient, catalog: Catalog) -> None:
    assert erp.list_sales_channels() == list(catalog.sales_channels)
    assert erp.list_skus() == list(catalog.skus)
    assert erp.list_suppliers() == list(catalog.suppliers)


def test_stock_levels_start_at_the_generators_opening_stock(erp: ErpClient, catalog: Catalog) -> None:
    opening = generate_opening_stock(catalog)
    levels = erp.stock_levels()
    assert len(levels) == len(catalog.sales_channels) * len(catalog.skus)
    assert {(s.sales_channel, s.sku): s.on_hand for s in levels} == {
        (channel, sku): units for channel, stock in opening.items() for sku, units in stock.items()
    }


def test_stock_levels_for_one_sales_channel(erp: ErpClient, catalog: Catalog) -> None:
    store = catalog.stores[0].code
    levels = erp.stock_levels(store)
    assert {s.sales_channel for s in levels} == {store}
    assert [s.sku for s in levels] == [s.code for s in catalog.skus]


def test_stock_levels_for_an_unknown_sales_channel_are_refused(erp: ErpClient) -> None:
    with pytest.raises(ErpRefusal):
        erp.stock_levels("NOWHERE")


def test_placing_a_reorder_sends_it_to_the_skus_supplier_at_unit_cost(
    erp: ErpClient, catalog: Catalog
) -> None:
    sku = catalog.skus[0]
    store = catalog.stores[0].code

    reorder = erp.place_reorder(sales_channel=store, sku=sku.code, quantity=sku.case_pack * 3)

    assert reorder.status is ReorderStatus.PLACED
    assert (reorder.sales_channel, reorder.sku, reorder.quantity) == (store, sku.code, sku.case_pack * 3)
    assert reorder.supplier_code == sku.supplier_code
    assert reorder.unit_cost == sku.unit_cost
    assert reorder.cost == round(sku.case_pack * 3 * sku.unit_cost, 2)
    assert erp.get_reorder(reorder.reorder_id) == reorder
    assert erp.list_reorders() == [reorder]


def test_placing_a_reorder_leaves_stock_on_hand_unchanged(erp: ErpClient, catalog: Catalog) -> None:
    online_shop = catalog.online_shop.code
    before = erp.stock_levels(online_shop)

    erp.place_reorder(sales_channel=online_shop, sku=catalog.skus[1].code, quantity=4)

    assert erp.stock_levels(online_shop) == before


def test_reorders_get_distinct_ids_and_are_listed_oldest_first(erp: ErpClient, catalog: Catalog) -> None:
    first = erp.place_reorder(sales_channel=catalog.stores[0].code, sku=catalog.skus[0].code, quantity=6)
    second = erp.place_reorder(sales_channel=catalog.stores[1].code, sku=catalog.skus[2].code, quantity=2)

    assert first.reorder_id != second.reorder_id
    assert erp.list_reorders() == [first, second]


@pytest.mark.parametrize(
    ("sales_channel", "sku", "quantity"),
    [("NOWHERE", None, 6), (None, "NO-SUCH-SKU", 6), (None, None, 0), (None, None, -5)],
    ids=["unknown-sales-channel", "unknown-sku", "zero-quantity", "negative-quantity"],
)
def test_impossible_reorders_are_refused_and_never_placed(
    erp: ErpClient, catalog: Catalog, sales_channel: str | None, sku: str | None, quantity: int
) -> None:
    with pytest.raises(ErpRefusal):
        erp.place_reorder(
            sales_channel=sales_channel or catalog.stores[0].code,
            sku=sku or catalog.skus[0].code,
            quantity=quantity,
        )
    assert erp.list_reorders() == []


def test_cancelling_a_reorder_keeps_it_on_record_as_cancelled(erp: ErpClient, catalog: Catalog) -> None:
    kept = erp.place_reorder(sales_channel=catalog.stores[0].code, sku=catalog.skus[0].code, quantity=6)
    placed = erp.place_reorder(sales_channel=catalog.stores[0].code, sku=catalog.skus[1].code, quantity=6)

    cancelled = erp.cancel_reorder(placed.reorder_id)

    assert cancelled == placed.model_copy(update={"status": ReorderStatus.CANCELLED})
    assert erp.get_reorder(placed.reorder_id) == cancelled
    assert erp.list_reorders() == [kept, cancelled]


def test_a_cancelled_reorder_cannot_be_cancelled_again(erp: ErpClient, catalog: Catalog) -> None:
    reorder = erp.place_reorder(sales_channel=catalog.stores[0].code, sku=catalog.skus[0].code, quantity=6)
    erp.cancel_reorder(reorder.reorder_id)

    with pytest.raises(ErpRefusal):
        erp.cancel_reorder(reorder.reorder_id)


def test_unknown_reorders_are_refused(erp: ErpClient) -> None:
    with pytest.raises(ErpRefusal):
        erp.get_reorder("RO-99999")
    with pytest.raises(ErpRefusal):
        erp.cancel_reorder("RO-99999")
