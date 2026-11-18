"""Seeded, deterministic generator for the Client and its Uploads (ADR 0005)."""

from retail_ops_agent.generator.catalog import generate_catalog
from retail_ops_agent.generator.defects import (
    PLANTABLE_DEFECTS,
    DefectPlan,
    GeneratedUploads,
    GroundTruth,
    PlantedDefect,
    generate_uploads,
)
from retail_ops_agent.generator.formats import (
    online_shop_order_lines_csv,
    online_shop_stock_snapshot_csv,
    store_inventory_csv,
    store_sales_csv,
    upload_csv,
)
from retail_ops_agent.generator.history import (
    History,
    InventoryRow,
    OrderLine,
    Restock,
    SalesRow,
    generate_history,
)
from retail_ops_agent.generator.resubmissions import (
    PlantedResubmission,
    ResubmissionKind,
    ResubmissionPlan,
    resubmission_csv,
)

__all__ = [
    "PLANTABLE_DEFECTS",
    "DefectPlan",
    "GeneratedUploads",
    "GroundTruth",
    "History",
    "InventoryRow",
    "OrderLine",
    "PlantedDefect",
    "PlantedResubmission",
    "Restock",
    "ResubmissionKind",
    "ResubmissionPlan",
    "SalesRow",
    "generate_catalog",
    "generate_history",
    "generate_uploads",
    "online_shop_order_lines_csv",
    "online_shop_stock_snapshot_csv",
    "resubmission_csv",
    "store_inventory_csv",
    "store_sales_csv",
    "upload_csv",
]
