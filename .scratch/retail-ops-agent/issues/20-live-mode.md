# 20: Live Mode

**What to build:** Each Visitor gets their own in-memory sandbox of Cobalt Home (BI store, fake ERP, clock) where they can run Ops Days with real models, approve or reject, undo, upload their own CSV, and reset. A shared free-tier key with a rate limit is used first, then the Visitor is asked for their own key.

**Blocked by:** 18

**Status:** ready-for-agent

- [ ] Each Visitor's sandbox is isolated and seeded from the generator; nothing is stored on the server
- [ ] "Run day", approve/reject, undo, uploading their own CSV and reset all work through the Ops Day boundary
- [ ] The shared key is rate-limited; once the limit is reached the Visitor is asked for their own key, which is never stored
- [ ] A dashboard smoke test passes in Live Mode against a seeded sandbox (scripted model)

## Comments
