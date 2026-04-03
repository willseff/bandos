import os
from typing import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools.agent_tool import AgentTool
from google.genai import types as genai_types

from .sub_agents.image_generator import parallel_image_generator
from .sub_agents.judge_agent import judge_agent
from .sub_agents.prompt_engineer import prompt_engineer
from .tools.brand_db import load_brand_context


post_processor = LlmAgent(
    name="PostProcessor",
    model="gemini-2.5-flash",
    instruction="""
You are a brand image post-processor running as part of an automated pipeline.
Do NOT greet the user or ask for clarification. Immediately execute your task.

Read state["winner_image"] for the base image path and state["brand_context"] for
brand colors, fonts, and asset rules. Apply final touches using available tools:
- render_text: add headlines or captions using real brand fonts and colors
- composite: overlay the brand logo at the correct position and scale
- resize: crop/pad to the required output dimensions

Follow all brand rules strictly. When done, output only the final image path.
""",
    output_key="final_image",
)


class ImageResultAgent(BaseAgent):
    """Reads winner_image from state and yields it as an inline image event."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        winner = ctx.session.state.get("winner_image")
        if not winner:
            yield Event(
                author=self.name,
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(text="No image was generated.")],
                ),
            )
            return

        file_path = winner.get("file_path") if isinstance(winner, dict) else winner
        if not file_path or not os.path.exists(file_path):
            yield Event(
                author=self.name,
                content=genai_types.Content(
                    role="model",
                    parts=[genai_types.Part(text=f"Image file not found: {file_path}")],
                ),
            )
            return

        with open(file_path, "rb") as f:
            image_bytes = f.read()

        yield Event(
            author=self.name,
            content=genai_types.Content(
                role="model",
                parts=[
                    genai_types.Part(text="Here's your generated image:"),
                    genai_types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                ],
            ),
        )


image_result_agent = ImageResultAgent(
    name="ImageResultAgent",
    description="Returns the winner image inline in the chat.",
)

refinement_loop = LoopAgent(
    name="RefinementLoop",
    sub_agents=[prompt_engineer, parallel_image_generator, judge_agent],
    max_iterations=3,
)

_pipeline = SequentialAgent(
    name="ImagePipeline",
    sub_agents=[refinement_loop, post_processor, image_result_agent],
    description="Runs the full brand image generation pipeline.",
)


def _load_brand_on_start(callback_context: CallbackContext) -> None:
    """Auto-load brand context from brand_id if not already set."""
    state = callback_context.state
    if not state.get("brand_context") and state.get("brand_id"):
        state["brand_context"] = load_brand_context(state["brand_id"])


root_agent = LlmAgent(
    name="BrandImageAgent",
    model="gemini-2.5-flash",
    instruction="""
You are a brand image generation assistant. You help users create brand-compliant images.

When the user asks you to generate, create, or make an image (or anything visual),
call the ImagePipeline tool with their request.
Before calling it, write state["user_prompt"] with the user's request.

For anything else (greetings, questions, clarifications), just respond conversationally.
The brand is already loaded — you don't need to ask for brand details.
""",
    tools=[AgentTool(agent=_pipeline)],
    before_agent_callback=_load_brand_on_start,
)
