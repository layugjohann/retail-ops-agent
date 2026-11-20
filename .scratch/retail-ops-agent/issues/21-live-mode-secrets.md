# 21: Turn on Live Mode in the deployment (human)

**What to build:** A human step: add the shared free-tier key as a Streamlit secret and try Live Mode on the public deployment.

**Blocked by:** 19, 20, 25

**Status:** ready-for-human

- [x] Shared key set as a Streamlit secret
- [ ] Live Mode tried end to end on the public URL: Run day, approve, undo, reset
- [ ] Behaviour when the rate limit is hit confirmed

## Comments

**2026-11-20:** After the Live Mode merge, the deployed app raised `ImportError: cannot import name 'InMemoryDataSource' from 'retail_ops_agent.data_source'`, and a reboot did not clear it. The server's checkout had a `data_source.py` older than the `live.py` beside it (`main` has both). Deleting the app and deploying it again from `main` (fresh clone) fixed it, and the redeploy also moved it from Python 3.14 to 3.13 to match the deploy wizard. The secrets were pasted into Advanced settings while creating the app: `GROQ_API_KEY`, with `LIVE_SHARED_RUNS = "1"` for now so the limit can be hit on purpose. Live Mode loads on the public URL.
