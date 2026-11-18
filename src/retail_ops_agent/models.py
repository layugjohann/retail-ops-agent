"""Choosing models at the edge (dashboard, CLI), from environment variables.

Free-tier Groq or Gemini are the defaults (ADR 0001). With no key at all, an offline scripted
model stands in, so nothing needs a paid service or even a network to run.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic_ai.models.test import TestModel

from retail_ops_agent.ops_day import Models

DEFAULT_GROQ_MODEL = "groq:openai/gpt-oss-120b"
DEFAULT_GEMINI_MODEL = "google:gemini-3.5-flash-lite"


def offline_intake_model() -> TestModel:
    """A scripted Intake model that reports no Defects beyond the deterministic checks."""
    return TestModel(custom_output_args={"defects": [], "uploader_message": None})


OFFLINE_NOTE = "Not investigated: no model key is set, so an offline scripted model stood in."


def offline_analyst_model() -> TestModel:
    """A scripted Analyst model that says plainly it investigated nothing."""
    return TestModel(
        call_tools=[],
        custom_output_args={
            "cause": OFFLINE_NOTE,
            "evidence": ["See the statistics that flagged the Anomaly."],
            "recommended_action": {
                "kind": "reorder",
                "description": "Reorder the SKU; the inventory planner decides in the Approval Queue.",
            },
        },
    )


# The quantity the offline scripted Ops model proposes. It is never investigated, so like every
# Reorder it goes through the Action policy: above the Auto-approval Limit it waits for a person.
OFFLINE_REORDER_QUANTITY = 48


def offline_ops_model() -> TestModel:
    """A scripted Ops model that proposes a fixed Reorder for the Approval Queue."""
    return TestModel(
        custom_output_args={
            "kind": "reorder",
            "quantity": OFFLINE_REORDER_QUANTITY,
            "subject": "Stockout risk flagged: Reorder proposed",
            "body": "Days of cover fell below the Lead Time. " + OFFLINE_NOTE,
        },
    )


def model_name_from_environment(env: Mapping[str, str]) -> str | None:
    """The real model the environment's keys reach: RETAIL_OPS_MODEL, else free-tier Groq, else
    free-tier Gemini. None when no key is set."""
    override = env.get("RETAIL_OPS_MODEL", "").strip()
    if override:
        return override
    if env.get("GROQ_API_KEY", "").strip():
        return DEFAULT_GROQ_MODEL
    if env.get("GOOGLE_API_KEY", "").strip() or env.get("GEMINI_API_KEY", "").strip():
        return DEFAULT_GEMINI_MODEL
    return None


def models_from_environment(env: Mapping[str, str]) -> tuple[Models, str]:
    """Pick models from the environment. Returns the models and a label describing the choice."""
    name = model_name_from_environment(env)
    if name is not None:
        return Models(intake=name, analyst=name, ops=name), name
    offline = Models(intake=offline_intake_model(), analyst=offline_analyst_model(), ops=offline_ops_model())
    return offline, "offline scripted model (no key set)"
