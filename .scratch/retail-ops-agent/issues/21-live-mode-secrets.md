# 21: Turn on Live Mode in the deployment (human)

**What to build:** A human step: add the shared free-tier key as a Streamlit secret and try Live Mode on the public deployment.

**Blocked by:** 19, 20, 25

**Status:** done

- [x] Shared key set as a Streamlit secret
- [x] Live Mode tried end to end on the public URL: Run day, approve, undo, reset
- [x] Behaviour when the rate limit is hit confirmed

## Comments

**2026-11-20:** After the Live Mode merge, the deployed app raised `ImportError: cannot import name 'InMemoryDataSource' from 'retail_ops_agent.data_source'`, and a reboot did not clear it. The server's checkout had a `data_source.py` older than the `live.py` beside it (`main` has both). Deleting the app and deploying it again from `main` (fresh clone) fixed it, and the redeploy also moved it from Python 3.14 to 3.13 to match the deploy wizard. The secrets were pasted into Advanced settings while creating the app: `GROQ_API_KEY`, with `LIVE_SHARED_RUNS = "1"` for now so the limit can be hit on purpose. Live Mode loads on the public URL.

**2026-11-20:** The first Run day on the public URL failed: gpt-oss-120b returns its answer through a tool it calls `json`. That was fixed in Issue 25 (PR #20), and the app was rebooted after the merge. Then, on https://cobalt-home-ops.streamlit.app/:

- Run day for 2026-11-14 ran with `groq:openai/gpt-oss-120b (shared key)`: 14 Uploads, 0 Anomalies, 0 Reorders, 0 Audit Log entries.
- The seeded Reorder `A-00001` had expired by then (48 simulated hours), so Reset sandbox was used to bring it back: approved once, then reset and rejected. Undo on an Audit Log entry worked, and reset went back to the seeded state.
- With `LIVE_SHARED_RUNS = "1"`, the second Run day showed "The shared free-tier key's limit of 1 Ops Day every 24 hours is reached". A different Groq key in the Visitor's key field ran the day "(your key)". After a refresh the key field was empty.

The shared key was first in Groq's Default Project together with other keys, so it shared their usage and limits. It was moved to its own `cobalt-home-public` project: a new key went into the Streamlit secrets, and the old one was deleted. One Ops Day with no Anomalies used 19.5k tokens on the new project; days with Anomalies cost more, so the plan is about 25k a day. The limits for `openai/gpt-oss-120b` are 30 requests/min, 1K requests/day, 8K tokens/min and 200K tokens/day. `LIVE_SHARED_RUNS` is now `"6"` (about 150k tokens and 120 requests a day), and the app shows "6 left now".

Still open: 8K tokens/min is less than half an Ops Day, so the Groq client waits and retries partway through a day. A per-minute 429 that outlasts its retries marks the shared key used up for every Visitor (see Issue 25's open finding).
