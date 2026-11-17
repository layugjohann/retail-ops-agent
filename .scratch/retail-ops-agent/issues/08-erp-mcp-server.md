# 08: ERP MCP server, fake ERP and contract tests

**What to build:** The mock ERP as a standalone MCP server (ADR 0006) exposing SKUs, stock, Suppliers and Reorders, plus an in-memory fake. Both sit behind one ERP client interface, and one contract test suite runs against both so the fake can't drift from the server.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] The MCP server exposes: read SKUs, stock levels and Suppliers; place, read and cancel Reorders
- [ ] It is seeded from the same Cobalt Home catalog
- [ ] The ERP client interface has two implementations: an MCP client and an in-memory fake
- [ ] One contract test suite passes against both
- [ ] README section on connecting the server from an MCP client such as Claude Desktop

## Comments
