# 22: n8n workflow files

**What to build:** A local n8n setup in Docker that triggers an Ops Day on a schedule and forwards notifications. All logic stays in tested code (n8n is only a trigger), and the exported workflow is committed.

**Blocked by:** 04
**Stacked on:** issue/20-live-mode

**Status:** done
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/19

- [x] An entry point n8n can call to run an Ops Day (CLI or local HTTP)
- [x] A Docker Compose file for local n8n
- [x] Exported workflow JSON committed: scheduled trigger → run Ops Day → forward Uploader messages and alerts
- [x] The workflow contains no business rules
- [x] README instructions for running it

## Comments

Usage: Implementer 10 input, 1,129 output, 24,138 cache creation, 149,051 cache read; Review Session unknown.

**Review Session: Non-critical Findings**

- If an Ops Day fails part-way on a model error after Intake already messaged an Uploader or an alert went out, those notifications stay in notifier.sent but are never forwarded: the next successful run only returns notifications sent from the start of that call (trigger.py run_next_day).
- Handler._run catches only NoDaysLeft and AgentRunError; any other error closes the HTTP connection without a JSON reply naming the problem, instead of returning a 500.
- POST /inbox stores any JSON object in memory with no size limit, and none of the endpoints are authenticated. Fine on 127.0.0.1, but the README tells Linux users to bind 0.0.0.0, which exposes /ops-day/run and /inbox to the network; worth a warning in the README.
- `make n8n` runs `import:workflow` right after `docker compose up -d`, before n8n may have finished setting up its database, so the first import can fail.
- docker-compose.yml defaults N8N_VERSION to `latest`; pinning a tested version would keep the exported workflow's node typeVersions working on future n8n releases.
- No GLOSSARY.md entry was added for the new trigger and local inbox, though they are arguably not domain terms.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-22-2026-11-20T05-23-56-082Z.log`).

Usage: Body writer 2 input, 1,472 output, 34,238 cache creation, 11,842 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/19

Stacked on Base Issue 20: this Pull Request targets `issue/20-live-mode`, the branch of https://github.com/layugjohann/retail-ops-agent/pull/18. Merge that Pull Request first.
