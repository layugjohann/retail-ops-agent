# 08: ERP MCP server, fake ERP and contract tests

**What to build:** The mock ERP as a standalone MCP server (ADR 0006) exposing SKUs, stock, Suppliers and Reorders, plus an in-memory fake. Both sit behind one ERP client interface, and one contract test suite runs against both so the fake can't drift from the server.

**Blocked by:** 01
**Stacked on:** issue/07-eval-harness-intake-evals

**Status:** in-progress

- [ ] The MCP server exposes: read SKUs, stock levels and Suppliers; place, read and cancel Reorders
- [ ] It is seeded from the same Cobalt Home catalog
- [ ] The ERP client interface has two implementations: an MCP client and an in-memory fake
- [ ] One contract test suite passes against both
- [ ] README section on connecting the server from an MCP client such as Claude Desktop

## Comments

Usage: Implementer 52 input, 20,730 output, 76,892 cache creation, 1,685,518 cache read; Review Session 30 input, 9,461 output, 51,428 cache creation, 792,124 cache read.

**Review Session: Non-critical Findings**

- McpErpClient._call maps every error from the MCP server to ErpRefusal, so a crash inside the server is reported as the ERP turning a request down.
- McpErpClient imports the result-wrapper models (SalesChannelList, ReorderList, etc.) from erp_server, which couples the client to the server module; they would sit better in erp.py or a shared module.
- InMemoryErp.place_reorder names a SKU variable `item`, a word GLOSSARY.md lists to avoid for SKU.
- ReorderStatus (placed/cancelled) is a new domain concept that GLOSSARY.md doesn't define.
- McpErpClient._shut_down_loop calls loop.close() even if the thread didn't stop within the timeout, which would raise 'Cannot close a running event loop' instead of a clear message.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-08-2026-11-18T17-30-59-038Z.log`).

Usage: Body writer 2 input, 1,227 output, 38,426 cache creation, 11,615 cache read.
