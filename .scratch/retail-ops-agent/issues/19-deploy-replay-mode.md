# 19: Deploy Replay Mode (human)

**What to build:** A human step: deploy the dashboard to Streamlit Community Cloud using the wizard from ticket 18, so the project has a public link.

**Blocked by:** 18

**Status:** done

- [x] Streamlit Community Cloud account connected to the GitHub repo (make the repo public first if needed)
- [x] App deployed and opening in Replay Mode
- [x] Public URL added to the README

## Comments

**2026-11-20:** Deployed with `make deploy`. The repository is now public (git history checked for committed keys first; none found). The app is live at https://cobalt-home-ops.streamlit.app/ and opens in Replay Mode, with no secrets configured. The link is in the README. The recordings are still from the offline scripted model; re-recording them with a free-tier key is a follow-up.
