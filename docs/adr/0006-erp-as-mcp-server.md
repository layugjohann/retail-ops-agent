# The ERP is a standalone MCP server

The mock ERP (SKUs, stock levels, Suppliers, Reorders) is its own MCP server, and the agents reach it only over MCP. A real engagement would replace exactly this part with a server wrapping the Client's actual ERP (NetSuite, Odoo and so on), so the Deployment Playbook can describe that swap concretely. The same server also works from any MCP client, such as Claude Desktop.
