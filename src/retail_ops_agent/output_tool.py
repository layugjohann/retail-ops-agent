"""The output tool every agent returns its structured answer through.

gpt-oss-120b on Groq, the shared free-tier model (ADR 0001), returns its final answer through a tool
it calls "json", whatever the output tool is named. Under pydantic-ai's default name, final_result,
that is an unknown tool and the run fails. Naming the output tool "json" matches what the model
does. Other models call the tool by whatever name it has, so the name costs them nothing.
"""

from __future__ import annotations

from pydantic_ai import ToolOutput

OUTPUT_TOOL_NAME = "json"


def output_tool[T](output_type: type[T]) -> ToolOutput[T]:
    return ToolOutput(output_type, name=OUTPUT_TOOL_NAME)
