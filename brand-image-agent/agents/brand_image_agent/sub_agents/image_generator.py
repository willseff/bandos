import asyncio
import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from ..tools.generate_image import generate_image


class ParallelImageGenerator(BaseAgent):
    """
    Custom BaseAgent that reads engineered_prompts from state and fires
    N parallel image generation calls via asyncio.gather, then writes
    the results to state["generated_images"].
    """

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        raw_prompts = state.get("engineered_prompts", "[]")

        # engineered_prompts may be a JSON string or already a list
        if isinstance(raw_prompts, str):
            text = raw_prompts.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = {"prompts": []}
            prompts = parsed.get("prompts", parsed) if isinstance(parsed, dict) else parsed
        else:
            prompts = raw_prompts

        aspect_ratio = state.get("aspect_ratio", "1:1")
        resolution = state.get("resolution", "1K")

        async def _generate_one(variation: int, prompt: str) -> dict:
            result = await asyncio.to_thread(
                generate_image,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
            )
            return {
                "variation": variation,
                "engineered_prompt": prompt,
                "file_path": result["file_path"],
                "generation_time_ms": result["generation_time_ms"],
            }

        tasks = [_generate_one(i + 1, prompt) for i, prompt in enumerate(prompts)]
        generated = await asyncio.gather(*tasks)

        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"generated_images": list(generated)}),
        )


parallel_image_generator = ParallelImageGenerator(
    name="ParallelImageGenerator",
    description="Generates N images in parallel from engineered prompts.",
)
