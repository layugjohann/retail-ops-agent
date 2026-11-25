"""False positives for vulture (`make deadcode`): code that is used, but not in a way vulture can see.

Vulture counts a name as used if it appears here; `_` stands for whatever object owns it.
"""

# Pydantic fields that are only set, then serialized for a model, a Recording or a Scorecard.
_.price_per_unit  # analyst.DailySales
_.earlier_daily_units  # analyst.CategoryChange
_.client_name  # catalog.Catalog
_.safe_fixed_defects  # intake.UploadCheckSummary
_.free_text_cells  # intake.UploadCheckSummary
_.free_text_cells_omitted  # intake.UploadCheckSummary
_.finished_at  # evals.scorecard.Scorecard
_.notifications  # trigger.TriggerResult

# Enum members that are only ever parsed from data or compared by value.
_.READ  # audit_log.ActionTier, Tier 0
_.REJECT  # replay.Decision

# Request handler methods http.server calls by name (trigger.make_server).
_.do_GET
_.do_POST
_.log_message

# The context manager protocol fixes __exit__'s parameters (erp_mcp.McpErpClient).
_.exc_type
_.exc
_.tb

# A Pydantic AI setting the library reads (tests/conftest.py).
_.ALLOW_MODEL_REQUESTS
