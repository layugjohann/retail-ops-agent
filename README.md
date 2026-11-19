# retail-ops-agent

A working prototype of a forward-deployed engagement at **Cobalt Home**, a fictional home and
lifestyle retailer (6 Stores, an Online Shop, about 300 SKUs). All data is simulated.

See `GLOSSARY.md` for terms, `docs/adr/` for decisions and `.scratch/retail-ops-agent/spec.md`
for the spec.

## Develop

```sh
uv sync
make check       # ruff lint + format check, pyright, pytest
make dashboard   # Streamlit dashboard; opens in Replay Mode
make evals       # Golden Scenarios against real free-tier models; see evals/README.md
make record      # record Ops Days for Replay Mode
make deploy      # interactive wizard: deploy the dashboard to Streamlit Community Cloud
```

Model keys are optional and free-tier only; see `.env.example`.

## Replay Mode

The dashboard opens in Replay Mode: it plays back Recordings of real Ops Days with no model, no key
and no network call, so a Visitor can step through each Ops Day stage by stage (Intake, Load,
Detection, Investigation, Actions). The Recordings live in `src/retail_ops_agent/recordings/` and
include a Defect day (Safe Fixes, a Quarantine and a corrected resend), a stockout risk with a
Reorder under the Auto-approval Limit, and a stockout risk whose Reorder waits for and gets
Approval. Each Recording names the model its agents ran on.

`make record` runs each Recording's seeded sandbox through the Ops Day boundary again and rewrites
its JSON. With a free-tier key in `.env.local` the agents use that model, paced for its rate limit;
without one, the offline scripted model stands in. The sidebar switches to Live Mode, a seeded
sandbox run through the Ops Day boundary.

## Discovery and Hours Saved

`docs/discovery/` holds the simulated discovery documents: an engagement brief, personas, the
current manual processes step by step, and a baseline of manual timings. The baseline's
machine-readable form, `src/retail_ops_agent/baseline.json`, feeds the dashboard's Hours Saved:
the Audit Log entries of each baseline task's Action that no undo reversed, times its minutes each
time. Every timing is an assumption, marked as one, and shown next to the figure.

## The ERP MCP server

Cobalt Home's mock ERP runs as a standalone MCP server (ADR 0006). Its tools read Sales Channels,
SKUs, Suppliers and stock levels, and place, read and cancel Reorders. It is seeded from the same
generated Cobalt Home catalog as everything else, and its state lives in memory for as long as the
server runs.

```sh
uv run retail-ops-erp --seed 42   # speaks MCP over stdio
```

The agents and the Action policy never call these tools directly. They go through the ERP client
interface (`retail_ops_agent.erp.ErpClient`), which has two implementations: `McpErpClient`, which
talks to this server, and `InMemoryErp`, the fake used in tests and sandboxes. One contract suite
(`tests/test_erp_contract.py`) runs against both so the fake can't drift from the server. A real
engagement swaps this server for one that wraps the Client's own ERP (NetSuite, Odoo and so on)
and exposes the same tools.

### Connecting from Claude Desktop

Add the server to Claude Desktop's `claude_desktop_config.json` (Settings → Developer → Edit
Config), using the absolute path to your clone, and restart Claude Desktop:

```json
{
  "mcpServers": {
    "cobalt-home-erp": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/retail_ops_agent", "run", "retail-ops-erp", "--seed", "42"]
    }
  }
}
```

If Claude Desktop can't find `uv`, use its absolute path (`which uv`) as `command`. You can then ask
things like "Which SKUs does Store ST01 have fewer than 10 of?" or "Place a Reorder of 12 CH-0001
for ST01, then cancel it." The placing and cancelling tools are marked as writes, so the client
asks you before it runs them. Any other MCP client that can launch a stdio server works the same
way, and you can browse the tools with the MCP Inspector:

```sh
npx @modelcontextprotocol/inspector uv run retail-ops-erp --seed 42
```
