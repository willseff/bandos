import json
import base64
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext

INSTRUCTION = """
You are a brand compliance judge running as part of an automated pipeline.
Do NOT greet the user or ask for clarification. Immediately execute your task.

Read these values from state and act on them:
- state["generated_images"]: list of {variation, file_path, engineered_prompt}
- state["brand_context"]: brand rules, colors, assets
- state["score_threshold"]: minimum acceptable score (default 75)

Score each image 0-100:
- Start at 100
- Critical rule violation: -20 to -40 pts each (image cannot score above 59 with any critical violation)
- Warning violation: -5 to -15 pts each
- Suggestion violation: -1 to -5 pts each

Output ONLY a JSON object — no greeting, no explanation, no markdown fences:
{
  "results": [
    {
      "variation": 1,
      "score": 82,
      "violations": [{"rule_id": "...", "severity": "warning", "explanation": "..."}],
      "strengths": ["..."],
      "improvements": ["..."]
    }
  ]
}
"""


def _after_judge(callback_context: CallbackContext) -> None:
    """
    Parse judge output, pick the winner, and either escalate (threshold met)
    or write previous_feedback for the next loop iteration.
    """
    raw = callback_context.state.get("judge_results", "")
    if not raw:
        return

    # LlmAgent may wrap output in markdown fences
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return

    results = data.get("results", [])
    if not results:
        return

    best = max(results, key=lambda r: r.get("score", 0))
    threshold = callback_context.state.get("score_threshold", 75)
    generated_images = callback_context.state.get("generated_images", [])

    # Find the image entry for the best variation
    best_image = next(
        (img for img in generated_images if img.get("variation") == best["variation"]),
        None,
    )

    callback_context.state["best_result"] = best

    if best.get("score", 0) >= threshold:
        callback_context.state["winner_image"] = best_image
        callback_context.actions.escalate = True
    else:
        critical = [v for v in best.get("violations", []) if v.get("severity") == "critical"]
        all_improvements = best.get("improvements", [])
        callback_context.state["previous_feedback"] = {
            "best_score": best.get("score"),
            "critical_violations": critical,
            "improvements": all_improvements,
        }


judge_agent = LlmAgent(
    name="JudgeAgent",
    model="gemini-2.5-flash",
    instruction=INSTRUCTION,
    output_key="judge_results",
    after_agent_callback=_after_judge,
)
