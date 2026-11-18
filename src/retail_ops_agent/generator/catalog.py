"""Generates the Cobalt Home catalog from a seed."""

from __future__ import annotations

import random

from retail_ops_agent.catalog import Catalog, SalesChannel, SalesChannelKind, Sku, Supplier

CLIENT_NAME = "Cobalt Home"
SKU_COUNT = 300

_STORE_NAMES = (
    "Harbour Street",
    "Riverside",
    "Old Town",
    "Northgate",
    "Westfield",
    "Lakeview",
    "Market Square",
    "Hillcrest",
)

_SUPPLIER_NAMES = (
    "Brightwell Ceramics",
    "Nordlinen Textiles",
    "Oakfold Furniture",
    "Lumen & Co Lighting",
    "Kettle Lane Kitchenware",
    "Fernway Garden Goods",
    "Saltmarsh Candles",
)

# category -> (retail price range, possible case packs)
_CATEGORIES: dict[str, tuple[tuple[float, float], tuple[int, ...]]] = {
    "Kitchen": ((6.0, 60.0), (6, 12)),
    "Tableware": ((4.0, 40.0), (6, 12, 24)),
    "Bedding": ((15.0, 120.0), (4, 6)),
    "Bath": ((5.0, 45.0), (6, 12)),
    "Lighting": ((18.0, 150.0), (2, 4)),
    "Decor": ((8.0, 80.0), (4, 6, 12)),
    "Storage": ((7.0, 70.0), (4, 6)),
    "Garden": ((5.0, 90.0), (4, 6, 12)),
}

_ADJECTIVES = (
    "Linen",
    "Oak",
    "Stoneware",
    "Matte",
    "Woven",
    "Glazed",
    "Brushed",
    "Speckled",
    "Ribbed",
    "Coastal",
    "Nordic",
    "Rustic",
)

_NOUNS: dict[str, tuple[str, ...]] = {
    "Kitchen": ("Mixing Bowl", "Utensil Set", "Chopping Board", "Kettle", "Spice Rack"),
    "Tableware": ("Dinner Plate", "Mug", "Tumbler", "Serving Bowl", "Side Plate"),
    "Bedding": ("Duvet Cover", "Pillowcase Pair", "Throw", "Fitted Sheet", "Quilt"),
    "Bath": ("Bath Towel", "Hand Towel", "Bath Mat", "Soap Dish", "Robe"),
    "Lighting": ("Table Lamp", "Floor Lamp", "Pendant Shade", "String Lights", "Lantern"),
    "Decor": ("Vase", "Mirror", "Cushion", "Picture Frame", "Candle Holder"),
    "Storage": ("Basket", "Storage Box", "Shelf Unit", "Hook Rail", "Jar Set"),
    "Garden": ("Planter", "Watering Can", "Outdoor Cushion", "Bird Feeder", "Pot Set"),
}

_COLOURS = ("White", "Sage", "Charcoal", "Sand", "Terracotta", "Navy", "Natural")


def generate_catalog(seed: int) -> Catalog:
    """Build the Client's catalog. The same seed always gives the same catalog."""
    rng = random.Random(f"catalog:{seed}")

    store_names = rng.sample(_STORE_NAMES, 6)
    sales_channels = [
        SalesChannel(code=f"ST{i:02d}", name=f"{name} Store", kind=SalesChannelKind.STORE)
        for i, name in enumerate(store_names, start=1)
    ]
    sales_channels.append(SalesChannel(code="ONLINE", name="Online Shop", kind=SalesChannelKind.ONLINE_SHOP))

    supplier_count = rng.randint(4, 6)
    suppliers = [
        Supplier(code=f"SUP{i:02d}", name=name, lead_time_days=rng.randint(3, 21))
        for i, name in enumerate(rng.sample(_SUPPLIER_NAMES, supplier_count), start=1)
    ]

    categories = list(_CATEGORIES)
    skus: list[Sku] = []
    seen_names: set[str] = set()
    for i in range(1, SKU_COUNT + 1):
        category = rng.choice(categories)
        (low, high), case_packs = _CATEGORIES[category]
        supplier = rng.choice(suppliers)
        retail_price = round(rng.uniform(low, high), 2)
        margin = rng.uniform(0.35, 0.6)
        name = _unique_name(rng, category, seen_names)
        skus.append(
            Sku(
                code=f"CH-{i:04d}",
                name=name,
                category=category,
                supplier_code=supplier.code,
                unit_cost=round(retail_price * (1 - margin), 2),
                retail_price=retail_price,
                case_pack=rng.choice(case_packs),
                lead_time_days=max(1, supplier.lead_time_days + rng.randint(-2, 2)),
            )
        )

    return Catalog(
        client_name=CLIENT_NAME,
        seed=seed,
        sales_channels=tuple(sales_channels),
        suppliers=tuple(suppliers),
        skus=tuple(skus),
    )


def _unique_name(rng: random.Random, category: str, seen: set[str]) -> str:
    while True:
        name = f"{rng.choice(_ADJECTIVES)} {rng.choice(_NOUNS[category])}, {rng.choice(_COLOURS)}"
        if name not in seen:
            seen.add(name)
            return name
        # Fall back to a numbered variant once the obvious combinations run out.
        numbered = f"{name} No. {len(seen) + 1}"
        if numbered not in seen:
            seen.add(numbered)
            return numbered
