# 01: Walking skeleton: one clean Store sales Upload end to end

**What to build:** Project scaffolding plus the thinnest complete path. A seeded generator creates the Cobalt Home catalog and one clean Store sales Upload. The Upload is submitted through the Ops Day boundary, and running the Ops Day takes it through Intake (Pydantic AI with a scripted test model) into DuckDB. A minimal Streamlit page shows sales and Upload status. This sets up the shape every later ticket extends: the Ops Day boundary with its dependencies passed in (models, ERP client, Notifier, Data Source, clock). See spec: Implementation Decisions.

**Blocked by:** None

**Status:** ready-for-agent

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
