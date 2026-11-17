# 18: Replay Mode

**What to build:** Record Ops Day outcomes from real runs and play them back in the dashboard with no model and no key, stepping through each stage (Intake, load, detection, Investigation, Actions). It becomes the dashboard's default. Includes a deploy wizard script for the human deploy step in ticket 19.

**Blocked by:** 10

**Status:** ready-for-agent

- [ ] Ops Day outcomes can be recorded and stored in the repository
- [ ] Replay Mode is the default and makes no model or network calls
- [ ] A Visitor can step through a recorded Ops Day stage by stage
- [ ] Recordings include at least a Defect day, a stockout with a Reorder, and an Approval
- [ ] An interactive wizard script walks the user through deploying to Streamlit Community Cloud
- [ ] A dashboard smoke test passes in Replay Mode

## Comments
