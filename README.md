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
make evals       # Golden Scenarios against real free-tier models; see evals/README.md
```

Model keys are optional and free-tier only; see `.env.example`.

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
