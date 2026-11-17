# Action Tiers are set by rules, not by the model's confidence

Unlike fixline, where the agent only ever proposed, the agents here act. Fixed rules assign every Action a Tier. Tier 0 (reads) and Tier 1 (internal and reversible: Quarantine, Safe Fix, alert, task) run on their own and are written to the Audit Log so they can be undone. Tier 2 (external or costly: Reorders, Supplier messages) needs Approval, except Reorders under the Auto-approval Limit. The model can recommend an Action but can never choose its Tier. A self-reported confidence score can't be checked, and it can be manipulated by text injected into an Upload.

## Consequences

"No Tier 2 Action without Approval" is a hard rule that the evals check, and it must hold 100% of the time. When an Upload is Superseded, Tier 1 Actions that relied on it are undone automatically. Tier 2 Actions that already went out are flagged for a human, never undone automatically.
