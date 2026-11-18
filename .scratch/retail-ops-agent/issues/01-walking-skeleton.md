# 01: Walking skeleton: one clean Store sales Upload end to end

**What to build:** Project scaffolding plus the thinnest complete path. A seeded generator creates the Cobalt Home catalog and one clean Store sales Upload. The Upload is submitted through the Ops Day boundary, and running the Ops Day takes it through Intake (Pydantic AI with a scripted test model) into DuckDB. A minimal Streamlit page shows sales and Upload status. This sets up the shape every later ticket extends: the Ops Day boundary with its dependencies passed in (models, ERP client, Notifier, Data Source, clock). See spec: Implementation Decisions.

**Blocked by:** None

**Status:** in-progress

- [ ] Python project managed by uv, with ruff (lint and format check), pyright and pytest. `make check` runs all of them and is the sandcastle-pro Gate
- [ ] `.env.example` lists the optional free-tier model keys (Groq, Gemini); nothing requires a paid service (ADR 0001)
- [ ] The catalog generator is seeded and deterministic: 6 Stores, 1 Online Shop, about 300 SKUs, 4–6 Suppliers, and each SKU has a Supplier, unit cost, retail price, case pack and lead time. Same seed gives identical output; a different seed gives different output
- [ ] Clean Store sales Uploads are generated with plausible seasonality
- [ ] Ops Day boundary: submit an Upload, run an Ops Day, read the outcome. The outcome shows the Upload as accepted
- [ ] Accepted data is queryable through the boundary's read views
- [ ] A Streamlit page shows sales by Sales Channel and the Upload status, reading only from the boundary
- [ ] Tests drive the Ops Day boundary with a scripted model; no network needed
- [ ] Code uses glossary terms (Sales Channel, Store, Online Shop, SKU, Supplier, Upload, Ops Day)

## Comments

Usage: Implementer 42 input, 32,707 output, 71,017 cache creation, 1,182,810 cache read; Review Session 14 input, 4,269 output, 230,630 cache creation, 1,445,627 cache read.

**Review Session: Non-critical Findings**

- intake.run_intake adds any Defects the model reports to the deterministic ones, and they are never checked against the Upload. A real model that invents a Defect would Quarantine a clean Upload, which goes against the spec's 'clean Upload never Quarantined'. Consider limiting model-reported Defects to ones the deterministic checks can confirm, or using the model only to write the Uploader message.
- ops_day.run_ops_day already Quarantines Uploads, but it writes no Audit Log entry and sends no Notification when the model gives no uploader_message. The offline model always gives none, so with it a Quarantined Upload is silent. Tickets 03 and 04 cover this; flagged so those tickets account for the path that already exists.
- .env.example says to copy it to .env.local, but nothing loads .env.local. models_from_environment reads only os.environ, so keys put there have no effect unless the user exports them.
- generator/sales.py generate_store_sales checks `store.kind is not SalesChannelKind.STORE` even though it already selected the store from catalog.stores, so the check can never fail. It is dead code.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-01-2026-11-18T05-47-53-996Z.log`).

Usage: Body writer 2 input, 1,221 output, 224,252 cache creation, 11,615 cache read.
