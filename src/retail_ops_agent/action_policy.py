"""The Action policy: a fixed rule table, not the model, decides each proposed Action's Tier (ADR 0002).

Tier 0 and Tier 1 Actions run on their own and are recorded in the Audit Log so they can be undone.
Tier 2 Actions wait in the Approval Queue for a human, except a Reorder whose cost is under the
Auto-approval Limit, which is approved by rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.audit_log import ACTION_TIERS, ActionTier, AuditAction
from retail_ops_agent.ops_agent import ActionProposal, ProposedActionKind

# Who alerts go to, by the kind of Anomaly. Fixed by rule; the model does not choose recipients.
ALERT_RECIPIENT = "inventory.planning@cobalthome.example"
REGIONAL_MANAGER = "regional.manager@cobalthome.example"
MERCHANDISING = "merchandising@cobalthome.example"
ALERT_RECIPIENTS: dict[AnomalyKind, str] = {
    AnomalyKind.STOCKOUT_RISK: ALERT_RECIPIENT,
    AnomalyKind.SALES_DROP: REGIONAL_MANAGER,
    AnomalyKind.SALES_SPIKE: MERCHANDISING,
    AnomalyKind.SLOW_MOVER: ALERT_RECIPIENT,
}

# The only kind of Anomaly a Reorder can answer. A sales drop is about a whole Sales Channel; a spike
# that does not threaten stock needs no Reorder (one that does is flagged as a stockout risk); and
# reordering a slow mover would only build its stock up. A Reorder proposed for any other kind is
# posted as an alert instead.
REORDERABLE = frozenset({AnomalyKind.STOCKOUT_RISK})

# A Reorder costing less than this is approved without a human. Configurable per Ops Day; this is the
# default for Cobalt Home, about a case or two of a typical SKU.
DEFAULT_AUTO_APPROVAL_LIMIT = 150.00

# Who approves a Reorder under the Auto-approval Limit, as the Audit Log records it.
AUTO_APPROVER = "Action policy (Auto-approval Limit)"

# Who replaces a pending Reorder with a newer Investigation's, and Expires a pending Action, as the
# Approval Queue and Audit Log record it.
QUEUE_RULES = "Action policy (Approval Queue rules)"

# Which Audit Log Action each kind of proposal becomes.
PROPOSED_ACTIONS: dict[ProposedActionKind, AuditAction] = {
    ProposedActionKind.ALERT: AuditAction.ALERT,
    ProposedActionKind.REORDER: AuditAction.REORDER,
}


class Route(StrEnum):
    # Tier 0 and Tier 1: runs now.
    RUN = "run"
    # Tier 2: waits in the Approval Queue for a human.
    QUEUE = "queue"
    # A Reorder under the Auto-approval Limit: approved by rule and placed now.
    AUTO_APPROVE = "auto_approve"


@dataclass(frozen=True)
class PolicyDecision:
    action: AuditAction
    tier: ActionTier
    route: Route

    @property
    def runs_on_its_own(self) -> bool:
        """Tier 0 and Tier 1 Actions run without waiting for Approval."""
        return self.route is Route.RUN


def decide(
    proposal: ActionProposal, *, anomaly_kind: AnomalyKind, cost: float | None, auto_approval_limit: float
) -> PolicyDecision:
    """The Action, Tier and route for a proposal, by rule. Nothing in the proposal's text is consulted.

    A Reorder proposed for an Anomaly no Reorder can answer, or with no SKU in the ERP to cost it,
    becomes an alert. cost is the Reorder's cost worked out from the ERP's unit cost, never taken
    from the model.
    """
    kind = proposal.kind
    if kind is ProposedActionKind.REORDER and (anomaly_kind not in REORDERABLE or cost is None):
        kind = ProposedActionKind.ALERT
    action = PROPOSED_ACTIONS[kind]
    tier = ACTION_TIERS[action]
    if tier < ActionTier.EXTERNAL:
        route = Route.RUN
    elif action is AuditAction.REORDER and cost is not None and cost < auto_approval_limit:
        route = Route.AUTO_APPROVE
    else:
        route = Route.QUEUE
    return PolicyDecision(action=action, tier=tier, route=route)
