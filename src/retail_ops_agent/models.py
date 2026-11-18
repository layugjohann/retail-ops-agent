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


def models_from_environment(env: Mapping[str, str]) -> tuple[Models, str]:
    """Pick models from the environment. Returns the models and a label describing the choice."""
    override = env.get("RETAIL_OPS_MODEL", "").strip()
    if override:
        return Models(intake=override), override
    if env.get("GROQ_API_KEY", "").strip():
        return Models(intake=DEFAULT_GROQ_MODEL), DEFAULT_GROQ_MODEL
    if env.get("GOOGLE_API_KEY", "").strip() or env.get("GEMINI_API_KEY", "").strip():
        return Models(intake=DEFAULT_GEMINI_MODEL), DEFAULT_GEMINI_MODEL
    return Models(intake=offline_intake_model()), "offline scripted model (no key set)"
