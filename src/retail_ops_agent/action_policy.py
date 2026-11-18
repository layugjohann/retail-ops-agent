"""The Action policy: a fixed rule table, not the model, decides each proposed Action's Tier (ADR 0002).

Tier 0 and Tier 1 Actions run on their own and are recorded in the Audit Log so they can be undone.
"""

from __future__ import annotations

from dataclasses import dataclass

from retail_ops_agent.audit_log import ACTION_TIERS, ActionTier, AuditAction
from retail_ops_agent.ops_agent import ActionProposal, ProposedActionKind

# Who alerts go to. Fixed by rule; the model does not choose recipients.
ALERT_RECIPIENT = "inventory.planning@cobalthome.example"

# Which Audit Log Action each kind of proposal becomes.
PROPOSED_ACTIONS: dict[ProposedActionKind, AuditAction] = {
    ProposedActionKind.ALERT: AuditAction.ALERT,
}


@dataclass(frozen=True)
class PolicyDecision:
    action: AuditAction
    tier: ActionTier

    @property
    def runs_on_its_own(self) -> bool:
        """Tier 0 and Tier 1 Actions run without waiting for Approval."""
        return self.tier < ActionTier.EXTERNAL


def decide(proposal: ActionProposal) -> PolicyDecision:
    """The Action and Tier for a proposal, by rule. Nothing in the proposal's text is consulted."""
    action = PROPOSED_ACTIONS[proposal.kind]
    return PolicyDecision(action=action, tier=ACTION_TIERS[action])
