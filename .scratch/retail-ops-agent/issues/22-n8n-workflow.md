# 22: n8n workflow files

**What to build:** A local n8n setup in Docker that triggers an Ops Day on a schedule and forwards notifications. All logic stays in tested code (n8n is only a trigger), and the exported workflow is committed.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] An entry point n8n can call to run an Ops Day (CLI or local HTTP)
- [ ] A Docker Compose file for local n8n
- [ ] Exported workflow JSON committed: scheduled trigger → run Ops Day → forward Uploader messages and alerts
- [ ] The workflow contains no business rules
- [ ] README instructions for running it

## Comments
