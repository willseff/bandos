from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent

from agents.brand_image_agent.sub_agents.image_generator import parallel_image_generator
from agents.brand_image_agent.sub_agents.judge_agent import judge_agent
from agents.brand_image_agent.sub_agents.prompt_engineer import prompt_engineer

# Post-processor: adds text, overlays logo, resizes to target dimensions.
# Has access to render_text, composite, resize, remove_background tools (added in later steps).
post_processor = LlmAgent(
    name="PostProcessor",
    model="gemini-2.5-flash",
    instruction="""
You are a brand image post-processor. You receive a winner image and the brand context.
Your job is to apply final touches using the available tools:
- render_text: add headlines or captions using real brand fonts and colors
- composite: overlay the brand logo at the correct position and scale
- resize: crop/pad to the required output dimensions

Read state["winner_image"] for the base image path and state["brand_context"] for
brand colors, fonts, and asset rules. Follow all brand rules strictly.

When done, write the final image path to state["final_image"].
""",
    output_key="final_image",
)

refinement_loop = LoopAgent(
    name="RefinementLoop",
    sub_agents=[prompt_engineer, parallel_image_generator, judge_agent],
    max_iterations=3,
)

root_agent = SequentialAgent(
    name="BrandImageAgent",
    sub_agents=[refinement_loop, post_processor],
    description="Generates brand-compliant images using iterative refinement.",
)
