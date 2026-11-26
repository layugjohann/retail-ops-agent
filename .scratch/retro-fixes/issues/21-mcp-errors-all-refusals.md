# 21: Every ERP MCP error is reported as the ERP refusing

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 08 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/erp_mcp.py:131-132`; `src/retail_ops_agent/erp_server.py:99-104`

`McpErpClient._call` raises `ErpRefusal` whenever a tool result has `is_error`. The server only turns `ErpRefusal` into a `ToolError`, but any other exception inside it also comes back with `is_error`, so a crash in the server is reported as the ERP turning a request down.

- [ ] Tell refusals apart from other server errors (for example by a marker in the refusal) and raise a different error for the rest.
