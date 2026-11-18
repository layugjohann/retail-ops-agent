# retail-ops-agent

A working prototype of a forward-deployed engagement at **Cobalt Home**, a fictional home and
lifestyle retailer (6 Stores, an Online Shop, about 300 SKUs). All data is simulated.

See `GLOSSARY.md` for terms, `docs/adr/` for decisions and `.scratch/retail-ops-agent/spec.md`
for the spec.

## Develop

```sh
uv sync
make check       # ruff lint + format check, pyright, pytest
make dashboard   # Streamlit dashboard over a seeded sandbox
```

Model keys are optional and free-tier only; see `.env.example`.
