# Brand Image Generation Agent — Architecture & Framework Spec

## Overview

An agentic framework that generates brand-compliant images using Gemini, with a SQLite brand asset database, rule enforcement, async parallel generation, and a React UI. The system uses an LLM-powered loop: **prompt engineering → parallel image generation → judging → retry if needed**.

---

## Tech Stack

| Layer | Tech | Notes |
|-------|------|-------|
| Frontend | React + Vite + TailwindCSS | Brand management dashboard + generation studio |
| Backend | FastAPI (Python) | API layer, agent orchestration, async generation |
| Database | SQLite via SQLAlchemy | Brand assets, rules, generation history |
| Image Gen | Google Gemini API (`gemini-2.0-flash-exp` or `imagen-3`) | Via `google-genai` SDK |
| LLM Agent | Gemini (text) | Prompt engineering + judging agents |
| Task Queue | Python `asyncio` + `asyncio.gather` | Parallel generation, no Celery needed initially |

---

## Project Structure

```
brand-image-agent/
├── backend/
│   ├── main.py                    # FastAPI app entrypoint
│   ├── config.py                  # Settings, API keys (env vars)
│   ├── database/
│   │   ├── models.py              # SQLAlchemy ORM models
│   │   ├── schema.sql             # Raw DDL for reference
│   │   ├── seed.py                # Seed data for demo brands
│   │   └── session.py             # DB session factory
│   ├── agents/
│   │   ├── orchestrator.py        # Main agentic loop controller
│   │   ├── prompt_engineer.py     # Translates request → image prompts
│   │   ├── judge.py               # Scores generated images against rules
│   │   └── brand_context.py       # Loads & formats brand context for agents
│   ├── tools/
│   │   ├── registry.py            # Tool registry — maps names to callables + schemas
│   │   ├── generate_image.py      # Text-to-image via Gemini Imagen
│   │   ├── generate_with_ref.py   # Image generation with reference image(s)
│   │   ├── composite.py           # Layer images together (logo on banner, etc.)
│   │   ├── outpaint.py            # Extend/expand image canvas
│   │   ├── resize.py              # Resize, crop, pad to target dimensions
│   │   └── remove_background.py   # Background removal via rembg
│   ├── services/
│   │   ├── gemini.py              # Gemini API wrapper (text + image gen)
│   │   ├── image_store.py         # Save/serve generated images
│   │   └── brand_service.py       # CRUD for brands, rules, assets
│   ├── routers/
│   │   ├── brands.py              # /api/brands/* endpoints
│   │   ├── generations.py         # /api/generate/* endpoints
│   │   └── assets.py              # /api/assets/* upload/manage
│   └── schemas/
│       ├── brand.py               # Pydantic models for brands
│       └── generation.py          # Pydantic models for generation requests/responses
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── BrandManager.jsx   # Brand CRUD + rule editor
│   │   │   ├── GenerationStudio.jsx  # Image generation interface
│   │   │   └── History.jsx        # Past generations browser
│   │   ├── components/
│   │   │   ├── BrandCard.jsx
│   │   │   ├── RuleEditor.jsx
│   │   │   ├── ColorPalette.jsx
│   │   │   ├── AssetUploader.jsx
│   │   │   ├── GenerationPanel.jsx
│   │   │   ├── ImageComparison.jsx # Side-by-side with scores
│   │   │   └── LiveProgress.jsx   # SSE-powered generation progress
│   │   └── hooks/
│   │       ├── useBrands.js
│   │       ├── useGeneration.js   # Manages SSE connection for live updates
│   │       └── useAssets.js
│   └── vite.config.js
├── generated/                     # Output images stored here
├── uploads/                       # Uploaded brand assets (logos, etc.)
├── .env                           # GEMINI_API_KEY, etc.
└── README.md
```

---

## SQLite Database Schema

```sql
-- Brands
CREATE TABLE brands (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    name TEXT NOT NULL,
    description TEXT,
    colors_json TEXT NOT NULL DEFAULT '{}',     -- {"primary": "#hex", "secondary": "#hex", ...}
    fonts_json TEXT NOT NULL DEFAULT '{}',       -- {"heading": "Font Name", "body": "Font Name"}
    metadata_json TEXT DEFAULT '{}',             -- Freeform brand metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Brand Rules (the core of rule enforcement)
CREATE TABLE brand_rules (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    brand_id TEXT NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    category TEXT NOT NULL,          -- 'color' | 'composition' | 'typography' | 'style' | 'tone' | 'content' | 'layout'
    severity TEXT NOT NULL DEFAULT 'warning',  -- 'critical' | 'warning' | 'suggestion'
    rule_text TEXT NOT NULL,          -- Human-readable rule description
    enforcement_prompt TEXT,          -- Optional: specific LLM prompt to check this rule
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Brand Assets (logos, icons, patterns, etc.)
CREATE TABLE brand_assets (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    brand_id TEXT NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL,         -- 'logo' | 'icon' | 'pattern' | 'photo' | 'illustration' | 'font_file'
    name TEXT NOT NULL,
    description TEXT,                 -- How/when to use this asset
    file_path TEXT NOT NULL,          -- Path to uploaded file
    mime_type TEXT,
    metadata_json TEXT DEFAULT '{}',  -- Dimensions, variants, usage notes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Generation Jobs (tracks each generation run)
CREATE TABLE generation_jobs (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    brand_id TEXT NOT NULL REFERENCES brands(id),
    user_prompt TEXT NOT NULL,         -- Original user request
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'engineering' | 'generating' | 'judging' | 'complete' | 'failed'
    config_json TEXT DEFAULT '{}',     -- {num_variations: 4, max_iterations: 3, ...}
    selected_image_id TEXT,            -- The winner
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Individual Generated Images (multiple per job)
CREATE TABLE generated_images (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    job_id TEXT NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
    iteration INTEGER NOT NULL DEFAULT 1,
    variation INTEGER NOT NULL,        -- 1, 2, 3, 4 within an iteration
    engineered_prompt TEXT NOT NULL,    -- The actual prompt sent to Gemini
    file_path TEXT,                     -- Path to generated image
    score REAL,                         -- Judge score 0-100
    rule_violations_json TEXT,          -- [{rule_id, severity, explanation}]
    judge_feedback TEXT,                -- LLM judge's full feedback
    generation_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_rules_brand ON brand_rules(brand_id);
CREATE INDEX idx_assets_brand ON brand_assets(brand_id);
CREATE INDEX idx_jobs_brand ON generation_jobs(brand_id);
CREATE INDEX idx_images_job ON generated_images(job_id);
```

---

## Agent Architecture

### The Agentic Loop

```
User Request: "Create a hero banner for our Q4 product launch"
        │
        ▼
┌─────────────────────┐
│  1. BRAND CONTEXT    │  Load brand from DB: colors, fonts, rules, assets
│     LOADER           │  Format into structured context for LLM
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  2. PROMPT           │  Gemini text call:
│     ENGINEER         │  - Takes user request + brand context
│     AGENT            │  - Outputs N detailed image gen prompts (variations)
│                      │  - Each prompt explicitly encodes brand rules
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  3. PARALLEL         │  asyncio.gather() fires N Gemini image gen calls
│     IMAGE GEN        │  - All run concurrently
│                      │  - Each produces one image
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  4. JUDGE            │  Gemini vision call (for each image):
│     AGENT            │  - Receives generated image + brand rules
│                      │  - Scores 0-100
│                      │  - Lists rule violations with severity
│                      │  - Provides improvement suggestions
└────────┬────────────┘
         ▼
┌─────────────────────┐
│  5. DECISION         │  If best score >= threshold (e.g., 75):
│                      │    → Return best image as winner
│                      │  If iteration < max_iterations:
│                      │    → Feed judge feedback back to step 2
│                      │  Else:
│                      │    → Return best available with warnings
└─────────────────────┘
```

### Agent: Prompt Engineer (`agents/prompt_engineer.py`)

```python
import json
from services.gemini import gemini_text

SYSTEM_PROMPT = """You are a brand-aware prompt engineer for image generation.
Given a user's request and comprehensive brand guidelines, generate {num_variations} 
distinct image generation prompts. Each prompt must:

1. Explicitly describe colors using the exact hex values from the brand palette
2. Specify typography style consistent with brand fonts
3. Follow ALL brand rules, especially those marked CRITICAL
4. Be detailed enough for Gemini image generation (describe composition, lighting, style)
5. Each variation should explore a DIFFERENT creative direction while staying on-brand

BRAND CONTEXT:
{brand_context}

{retry_context}

Respond with ONLY a JSON array of prompt strings. No explanation."""


async def engineer_prompts(
    user_request: str,
    brand_context: dict,
    num_variations: int = 4,
    previous_feedback: str | None = None,
) -> list[str]:
    retry_context = ""
    if previous_feedback:
        retry_context = f"""PREVIOUS ATTEMPT FEEDBACK (fix these issues):
{previous_feedback}"""

    response = await gemini_text(
        system=SYSTEM_PROMPT.format(
            num_variations=num_variations,
            brand_context=json.dumps(brand_context, indent=2),
            retry_context=retry_context,
        ),
        user_message=f"User request: {user_request}",
        response_format="json",
    )

    return json.loads(response)
```

### Agent: Judge (`agents/judge.py`)

```python
import json
import base64
from services.gemini import gemini_vision

JUDGE_SYSTEM = """You are a brand compliance judge for generated images.
You will receive an image and the brand guidelines it should follow.
Score the image 0-100 and evaluate against EVERY rule.

BRAND RULES:
{rules}

BRAND COLORS: {colors}
BRAND FONTS: {fonts}

Respond with ONLY this JSON structure:
{{
  "score": <0-100>,
  "violations": [
    {{
      "rule_id": "<id>",
      "severity": "critical|warning|suggestion",
      "explanation": "<what's wrong>"
    }}
  ],
  "strengths": ["<what it does well>"],
  "improvements": "<specific suggestions for the prompt engineer to fix>"
}}"""


async def judge_image(
    image_path: str,
    brand_context: dict,
) -> dict:
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    response = await gemini_vision(
        system=JUDGE_SYSTEM.format(
            rules=json.dumps(brand_context["rules"], indent=2),
            colors=json.dumps(brand_context["colors"]),
            fonts=json.dumps(brand_context["fonts"]),
        ),
        image_base64=image_data,
        user_message="Judge this image against the brand guidelines.",
        response_format="json",
    )

    return json.loads(response)
```

### Orchestrator (`agents/orchestrator.py`)

```python
import asyncio
from agents.prompt_engineer import engineer_prompts
from agents.judge import judge_image
from agents.brand_context import load_brand_context
from services.gemini import gemini_generate_image
from services.image_store import save_image
from database.session import get_db

# SSE callback type for streaming progress to frontend
type ProgressCallback = Callable[[str, dict], None]


async def run_generation(
    job_id: str,
    brand_id: str,
    user_prompt: str,
    num_variations: int = 4,
    max_iterations: int = 3,
    score_threshold: float = 75.0,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Main agentic loop."""

    db = get_db()
    brand_ctx = await load_brand_context(brand_id, db)

    def emit(event, data):
        if on_progress:
            on_progress(event, data)

    best_result = None
    previous_feedback = None

    for iteration in range(1, max_iterations + 1):
        emit("status", {"stage": "engineering", "iteration": iteration})

        # Step 1: Generate prompts
        prompts = await engineer_prompts(
            user_request=user_prompt,
            brand_context=brand_ctx,
            num_variations=num_variations,
            previous_feedback=previous_feedback,
        )

        emit("prompts", {"iteration": iteration, "prompts": prompts})

        # Step 2: Generate images in parallel
        emit("status", {"stage": "generating", "iteration": iteration})

        async def generate_one(prompt: str, variation: int):
            image_bytes = await gemini_generate_image(prompt)
            path = save_image(job_id, iteration, variation, image_bytes)
            return {"prompt": prompt, "variation": variation, "path": path}

        results = await asyncio.gather(
            *[generate_one(p, i + 1) for i, p in enumerate(prompts)],
            return_exceptions=True,
        )

        # Filter out failures
        successful = [r for r in results if isinstance(r, dict)]

        if not successful:
            emit("error", {"message": "All generations failed", "iteration": iteration})
            continue

        # Step 3: Judge all images in parallel
        emit("status", {"stage": "judging", "iteration": iteration})

        async def judge_one(result: dict):
            verdict = await judge_image(result["path"], brand_ctx)
            return {**result, **verdict}

        judged = await asyncio.gather(
            *[judge_one(r) for r in successful],
            return_exceptions=True,
        )

        judged = [j for j in judged if isinstance(j, dict)]

        # Sort by score descending
        judged.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Persist to DB
        for j in judged:
            await db.save_generated_image(
                job_id=job_id,
                iteration=iteration,
                variation=j["variation"],
                engineered_prompt=j["prompt"],
                file_path=j["path"],
                score=j["score"],
                rule_violations=j.get("violations", []),
                judge_feedback=j.get("improvements", ""),
            )

        emit("judged", {
            "iteration": iteration,
            "results": [
                {"variation": j["variation"], "score": j["score"],
                 "violations": j.get("violations", []), "path": j["path"]}
                for j in judged
            ],
        })

        current_best = judged[0]

        if best_result is None or current_best["score"] > best_result["score"]:
            best_result = current_best

        # Step 4: Check if good enough
        if best_result["score"] >= score_threshold:
            emit("complete", {"winner": best_result, "iterations_used": iteration})
            return best_result

        # Step 5: Build feedback for retry
        critical_violations = [
            v for v in best_result.get("violations", [])
            if v["severity"] == "critical"
        ]

        previous_feedback = (
            f"Best score so far: {best_result['score']}/100\n"
            f"Critical violations to fix:\n"
            + "\n".join(f"- {v['explanation']}" for v in critical_violations)
            + f"\nJudge suggestions: {best_result.get('improvements', '')}"
        )

    # Exhausted iterations
    emit("complete", {"winner": best_result, "iterations_used": max_iterations, "threshold_met": False})
    return best_result
```

---

## Gemini Service (`services/gemini.py`)

```python
"""Wrapper around Google Gemini API for text, vision, and image generation."""

import os
import asyncio
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def gemini_text(
    system: str,
    user_message: str,
    model: str = "gemini-2.5-flash",
    response_format: str = "text",
) -> str:
    """Text-only Gemini call. Use for prompt engineering & decisions."""

    config = {"system_instruction": system}
    if response_format == "json":
        config["response_mime_type"] = "application/json"

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=user_message,
        config=config,
    )
    return response.text


async def gemini_vision(
    system: str,
    image_base64: str,
    user_message: str,
    model: str = "gemini-2.5-flash",
    response_format: str = "text",
) -> str:
    """Vision call — send image + text to Gemini for judging."""

    config = {"system_instruction": system}
    if response_format == "json":
        config["response_mime_type"] = "application/json"

    contents = [
        {"mime_type": "image/png", "data": image_base64},
        user_message,
    ]

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=contents,
        config=config,
    )
    return response.text


async def gemini_generate_image(
    prompt: str,
    model: str = "imagen-3.0-generate-002",
) -> bytes:
    """Generate an image using Gemini's Imagen model."""

    response = await asyncio.to_thread(
        client.models.generate_images,
        model=model,
        prompt=prompt,
        config={"number_of_images": 1},
    )

    # Returns the raw image bytes
    return response.generated_images[0].image.image_bytes
```

> **Note on Gemini image gen**: Google offers two paths — `imagen-3` for dedicated image generation, and `gemini-2.0-flash-exp` which can generate images inline in a multimodal response. The `imagen-3` path is more reliable for standalone generation. Check the latest docs for your API tier's availability.

---

## Tool Registry

The agents don't call APIs directly — they invoke **tools** through a registry. This is the core of the agentic design: the orchestrator (or the LLM itself via function calling) decides which tools to use and in what order based on the request.

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR / LLM (Gemini function calling)                │
│                                                              │
│  "I need to generate a hero banner with the brand logo       │
│   composited on top, then outpaint to 1920x1080"            │
│                                                              │
│  Tool plan:                                                  │
│   1. generate_image(prompt=..., aspect_ratio="16:9")         │
│   2. remove_background(image=logo.png)                       │
│   3. composite(base=step1, overlay=step2, position=top_left) │
│   4. outpaint(image=step3, target=1920x1080, fill=extend)   │
│   5. resize(image=step4, width=1920, height=1080, fit=cover) │
└──────────────────────────────────────────────────────────────┘
         │            │           │           │           │
         ▼            ▼           ▼           ▼           ▼
    ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐ ┌────────┐
    │ Gemini  │ │  rembg   │ │ Pillow  │ │ Gemini │ │ Pillow │
    │ Imagen  │ │          │ │         │ │ edit   │ │        │
    └─────────┘ └──────────┘ └─────────┘ └────────┘ └────────┘
```

### Tool Registry (`tools/registry.py`)

```python
"""Central tool registry. Each tool is a callable with a JSON schema
that can be passed to Gemini function calling or invoked directly."""

from dataclasses import dataclass, field
from typing import Callable, Any

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                # JSON Schema for inputs
    callable: Callable              # The async function to invoke
    returns: str                    # Description of output
    tags: list[str] = field(default_factory=list)  # For filtering: ["generation", "editing", "post-processing"]

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list_tools(self, tags: list[str] | None = None) -> list[Tool]:
        if tags:
            return [t for t in self._tools.values() if any(tag in t.tags for tag in tags)]
        return list(self._tools.values())

    def to_gemini_function_declarations(self, tags: list[str] | None = None) -> list[dict]:
        """Export tools as Gemini function calling declarations."""
        tools = self.list_tools(tags)
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in tools
        ]

    async def invoke(self, name: str, **kwargs) -> Any:
        tool = self._tools[name]
        return await tool.callable(**kwargs)


# Global registry instance
registry = ToolRegistry()
```

### Tool 1: `generate_image` — Text-to-Image

```python
# tools/generate_image.py
"""Generate an image from a text prompt using Gemini Imagen."""

import asyncio
import os
from google import genai
from tools.registry import registry, Tool

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def generate_image(
    prompt: str,
    negative_prompt: str = "",
    aspect_ratio: str = "1:1",
    style_preset: str | None = None,
    num_images: int = 1,
) -> list[dict]:
    """
    Generate image(s) from a text prompt.
    
    Returns list of {"image_bytes": bytes, "mime_type": str}
    """
    config = {
        "number_of_images": num_images,
        "aspect_ratio": aspect_ratio,
    }
    if negative_prompt:
        config["negative_prompt"] = negative_prompt
    if style_preset:
        config["style"] = style_preset

    response = await asyncio.to_thread(
        client.models.generate_images,
        model="imagen-3.0-generate-002",
        prompt=prompt,
        config=config,
    )

    return [
        {
            "image_bytes": img.image.image_bytes,
            "mime_type": "image/png",
        }
        for img in response.generated_images
    ]


registry.register(Tool(
    name="generate_image",
    description="Generate an image from a detailed text prompt. Best for creating new images from scratch. Supports aspect ratio control and negative prompts to exclude unwanted elements.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed image generation prompt. Should include style, colors, composition, subject, and mood."
            },
            "negative_prompt": {
                "type": "string",
                "description": "Things to exclude from the generated image (e.g., 'blurry, low quality, text artifacts').",
                "default": ""
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["1:1", "3:4", "4:3", "9:16", "16:9"],
                "description": "Aspect ratio. Use 16:9 for banners/headers, 9:16 for stories/mobile, 1:1 for social posts, 4:3 for presentations.",
                "default": "1:1"
            },
            "style_preset": {
                "type": "string",
                "enum": ["photorealistic", "digital_art", "illustration", "watercolor", "3d_render", "flat_design", "minimalist"],
                "description": "Optional style preset to guide the generation aesthetic."
            },
            "num_images": {
                "type": "integer",
                "description": "Number of images to generate (1-4).",
                "default": 1,
                "minimum": 1,
                "maximum": 4
            }
        },
        "required": ["prompt"]
    },
    callable=generate_image,
    returns="List of generated images as {image_bytes, mime_type} dicts.",
    tags=["generation"]
))
```

### Tool 2: `generate_with_reference` — Reference-Guided Generation

```python
# tools/generate_with_ref.py
"""Generate an image using one or more reference images for style/composition guidance."""

import asyncio
import base64
import os
from google import genai
from tools.registry import registry, Tool

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def generate_with_reference(
    prompt: str,
    reference_images: list[str],  # File paths to reference images
    reference_mode: str = "style",
    strength: float = 0.7,
    aspect_ratio: str = "1:1",
) -> list[dict]:
    """
    Generate image guided by reference image(s).
    
    Uses Gemini's multimodal generation: sends reference images + text prompt
    to generate a new image that matches the style/composition/subject of the references.
    
    reference_mode:
      - "style": Match the visual style, colors, and aesthetic of the reference
      - "composition": Match the layout and spatial arrangement
      - "subject": Generate something similar to the subject matter
      - "brand": Use reference as brand identity guide (logos, colors, patterns)
    """
    # Build multimodal content with reference images
    contents = []
    
    for ref_path in reference_images:
        with open(ref_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()
        contents.append({
            "mime_type": _get_mime_type(ref_path),
            "data": image_data,
        })

    mode_instructions = {
        "style": "Match the visual style, color palette, and artistic aesthetic of the reference image(s).",
        "composition": "Match the layout, spatial arrangement, and compositional structure of the reference image(s).",
        "subject": "Create something visually similar to the subject matter in the reference image(s).",
        "brand": "Use the reference image(s) as brand identity guides — match their colors, typography style, and design language.",
    }

    full_prompt = (
        f"Reference guidance ({reference_mode}): {mode_instructions[reference_mode]}\n"
        f"Strength of reference influence: {strength}/1.0\n\n"
        f"Generate this image: {prompt}"
    )
    contents.append(full_prompt)

    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.0-flash-exp",  # Multimodal model that can output images
        contents=contents,
        config={
            "response_modalities": ["image", "text"],
        },
    )

    results = []
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            results.append({
                "image_bytes": part.inline_data.data,
                "mime_type": part.inline_data.mime_type,
            })

    return results


def _get_mime_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {"png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/png")


registry.register(Tool(
    name="generate_with_reference",
    description="Generate a new image guided by one or more reference images. Use this when you need to match an existing brand style, replicate a composition, or create something visually similar to provided examples. Supports style transfer, composition matching, subject similarity, and brand identity guidance.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text prompt describing the desired image. The reference images provide visual guidance on top of this."
            },
            "reference_images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File paths to reference images (1-4 images). Can be brand assets, style examples, or composition templates."
            },
            "reference_mode": {
                "type": "string",
                "enum": ["style", "composition", "subject", "brand"],
                "description": "How to use the reference: 'style' matches aesthetics, 'composition' matches layout, 'subject' matches content, 'brand' matches brand identity.",
                "default": "style"
            },
            "strength": {
                "type": "number",
                "description": "How strongly the reference influences the output (0.0 = ignore reference, 1.0 = closely match reference).",
                "default": 0.7,
                "minimum": 0.0,
                "maximum": 1.0
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["1:1", "3:4", "4:3", "9:16", "16:9"],
                "default": "1:1"
            }
        },
        "required": ["prompt", "reference_images"]
    },
    callable=generate_with_reference,
    returns="List of generated images as {image_bytes, mime_type} dicts.",
    tags=["generation"]
))
```

### Tool 3: `composite` — Layer Images Together

```python
# tools/composite.py
"""Composite multiple images together — overlay logos, add brand elements, etc."""

from PIL import Image, ImageFilter
import io
from tools.registry import registry, Tool


async def composite(
    base_image_path: str,
    overlay_image_path: str,
    position: str = "center",
    x_offset: int = 0,
    y_offset: int = 0,
    overlay_scale: float = 0.2,
    opacity: float = 1.0,
    padding: int = 20,
    blend_mode: str = "normal",
) -> dict:
    """
    Layer an overlay image onto a base image.
    
    Common use cases:
    - Place a brand logo onto a generated banner
    - Add a watermark
    - Overlay a badge or icon
    - Composite brand elements onto photography
    """
    base = Image.open(base_image_path).convert("RGBA")
    overlay = Image.open(overlay_image_path).convert("RGBA")

    # Scale overlay relative to base image size
    target_width = int(base.width * overlay_scale)
    aspect = overlay.height / overlay.width
    target_height = int(target_width * aspect)
    overlay = overlay.resize((target_width, target_height), Image.LANCZOS)

    # Apply opacity
    if opacity < 1.0:
        alpha = overlay.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        overlay.putalpha(alpha)

    # Calculate position
    positions = {
        "top_left":      (padding + x_offset, padding + y_offset),
        "top_center":    ((base.width - overlay.width) // 2 + x_offset, padding + y_offset),
        "top_right":     (base.width - overlay.width - padding + x_offset, padding + y_offset),
        "center_left":   (padding + x_offset, (base.height - overlay.height) // 2 + y_offset),
        "center":        ((base.width - overlay.width) // 2 + x_offset, (base.height - overlay.height) // 2 + y_offset),
        "center_right":  (base.width - overlay.width - padding + x_offset, (base.height - overlay.height) // 2 + y_offset),
        "bottom_left":   (padding + x_offset, base.height - overlay.height - padding + y_offset),
        "bottom_center": ((base.width - overlay.width) // 2 + x_offset, base.height - overlay.height - padding + y_offset),
        "bottom_right":  (base.width - overlay.width - padding + x_offset, base.height - overlay.height - padding + y_offset),
    }

    pos = positions.get(position, positions["center"])

    # Composite
    if blend_mode == "multiply":
        # Darken blend — good for watermarks on light images
        from PIL import ImageChops
        region = base.crop((pos[0], pos[1], pos[0] + overlay.width, pos[1] + overlay.height))
        blended = ImageChops.multiply(region, overlay)
        base.paste(blended, pos)
    elif blend_mode == "screen":
        from PIL import ImageChops
        region = base.crop((pos[0], pos[1], pos[0] + overlay.width, pos[1] + overlay.height))
        blended = ImageChops.screen(region, overlay)
        base.paste(blended, pos)
    else:
        # Normal alpha composite
        base.paste(overlay, pos, overlay)

    # Export
    output = io.BytesIO()
    base.save(output, format="PNG")
    return {
        "image_bytes": output.getvalue(),
        "mime_type": "image/png",
        "dimensions": {"width": base.width, "height": base.height},
    }


registry.register(Tool(
    name="composite",
    description="Layer an overlay image (logo, badge, watermark) onto a base image. Supports 9-point positioning, scaling, opacity, padding, and blend modes. Use this to place brand logos onto generated images or add brand elements.",
    parameters={
        "type": "object",
        "properties": {
            "base_image_path": {
                "type": "string",
                "description": "Path to the base/background image."
            },
            "overlay_image_path": {
                "type": "string",
                "description": "Path to the overlay image (e.g., logo PNG with transparency)."
            },
            "position": {
                "type": "string",
                "enum": ["top_left", "top_center", "top_right", "center_left", "center", "center_right", "bottom_left", "bottom_center", "bottom_right"],
                "description": "Where to place the overlay on the base image.",
                "default": "center"
            },
            "x_offset": {"type": "integer", "description": "Horizontal pixel offset from the calculated position.", "default": 0},
            "y_offset": {"type": "integer", "description": "Vertical pixel offset from the calculated position.", "default": 0},
            "overlay_scale": {
                "type": "number",
                "description": "Scale of overlay relative to base image width (0.1 = 10% of base width, 0.5 = half).",
                "default": 0.2,
                "minimum": 0.01,
                "maximum": 1.0
            },
            "opacity": {
                "type": "number",
                "description": "Overlay opacity (0.0 = invisible, 1.0 = fully opaque).",
                "default": 1.0,
                "minimum": 0.0,
                "maximum": 1.0
            },
            "padding": {
                "type": "integer",
                "description": "Padding in pixels from image edges for corner/edge positions.",
                "default": 20
            },
            "blend_mode": {
                "type": "string",
                "enum": ["normal", "multiply", "screen"],
                "description": "Blend mode: 'normal' (alpha), 'multiply' (darken, good for watermarks on light), 'screen' (lighten).",
                "default": "normal"
            }
        },
        "required": ["base_image_path", "overlay_image_path"]
    },
    callable=composite,
    returns="Composited image as {image_bytes, mime_type, dimensions} dict.",
    tags=["post-processing"]
))
```

### Tool 4: `outpaint` — Extend Image Canvas

```python
# tools/outpaint.py
"""Extend an image beyond its current borders using Gemini's editing capabilities."""

import asyncio
import base64
import os
from PIL import Image
import io
from google import genai
from tools.registry import registry, Tool

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def outpaint(
    image_path: str,
    target_width: int,
    target_height: int,
    fill_prompt: str = "",
    anchor: str = "center",
) -> dict:
    """
    Extend an image to a larger canvas size.
    
    Strategy:
    1. Place original image on a larger canvas at the anchor position
    2. Create a mask of the empty regions
    3. Use Gemini to inpaint/outpaint the empty regions
    
    If Gemini edit API isn't available, falls back to:
    - Sending the padded image to Gemini multimodal with instructions to fill
    """
    original = Image.open(image_path).convert("RGBA")
    orig_w, orig_h = original.size

    # Create target canvas
    canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))

    # Calculate anchor position
    anchors = {
        "center":       ((target_width - orig_w) // 2, (target_height - orig_h) // 2),
        "top_left":     (0, 0),
        "top_center":   ((target_width - orig_w) // 2, 0),
        "top_right":    (target_width - orig_w, 0),
        "bottom_left":  (0, target_height - orig_h),
        "bottom_center":((target_width - orig_w) // 2, target_height - orig_h),
        "bottom_right": (target_width - orig_w, target_height - orig_h),
        "center_left":  (0, (target_height - orig_h) // 2),
        "center_right": (target_width - orig_w, (target_height - orig_h) // 2),
    }
    offset = anchors.get(anchor, anchors["center"])
    canvas.paste(original, offset)

    # Create mask (white = area to fill, black = keep original)
    mask = Image.new("L", (target_width, target_height), 255)  # All white
    mask.paste(0, offset + (offset[0] + orig_w, offset[1] + orig_h))  # Black where original is

    # Convert canvas to bytes for Gemini
    canvas_rgb = canvas.convert("RGB")
    buf = io.BytesIO()
    canvas_rgb.save(buf, format="PNG")
    canvas_bytes = buf.getvalue()
    canvas_b64 = base64.b64encode(canvas_bytes).decode()

    # Use Gemini multimodal to outpaint
    fill_instruction = fill_prompt or "Seamlessly extend the image content into the empty areas, maintaining consistent style, lighting, colors, and perspective."

    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.0-flash-exp",
        contents=[
            {"mime_type": "image/png", "data": canvas_b64},
            f"This image has transparent/empty regions around the edges that need to be filled. "
            f"The original image is placed at the {anchor}. "
            f"Fill the empty regions: {fill_instruction}\n"
            f"Output only the completed image.",
        ],
        config={"response_modalities": ["image", "text"]},
    )

    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            return {
                "image_bytes": part.inline_data.data,
                "mime_type": part.inline_data.mime_type,
                "dimensions": {"width": target_width, "height": target_height},
            }

    # Fallback: return the canvas with transparent edges
    return {
        "image_bytes": canvas_bytes,
        "mime_type": "image/png",
        "dimensions": {"width": target_width, "height": target_height},
    }


registry.register(Tool(
    name="outpaint",
    description="Extend an image beyond its current borders to a larger canvas size. Uses AI to seamlessly fill the new regions matching the original image's style and content. Great for adapting a square image to a banner, or extending a cropped photo.",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the source image to extend."
            },
            "target_width": {
                "type": "integer",
                "description": "Desired output width in pixels."
            },
            "target_height": {
                "type": "integer",
                "description": "Desired output height in pixels."
            },
            "fill_prompt": {
                "type": "string",
                "description": "Optional instructions for how to fill the extended regions (e.g., 'continue the gradient with brand blue tones').",
                "default": ""
            },
            "anchor": {
                "type": "string",
                "enum": ["center", "top_left", "top_center", "top_right", "center_left", "center_right", "bottom_left", "bottom_center", "bottom_right"],
                "description": "Where to anchor the original image on the larger canvas.",
                "default": "center"
            }
        },
        "required": ["image_path", "target_width", "target_height"]
    },
    callable=outpaint,
    returns="Extended image as {image_bytes, mime_type, dimensions} dict.",
    tags=["editing"]
))
```

### Tool 5: `resize` — Resize, Crop, Pad

```python
# tools/resize.py
"""Resize images with intelligent cropping, padding, and fit modes."""

from PIL import Image, ImageFilter
import io
from tools.registry import registry, Tool


async def resize(
    image_path: str,
    width: int,
    height: int,
    fit: str = "cover",
    background_color: str = "#000000",
    gravity: str = "center",
    quality: int = 95,
    output_format: str = "png",
) -> dict:
    """
    Resize an image to exact dimensions with multiple fit strategies.
    
    Fit modes:
    - "cover":   Scale up/down to fill target, crop overflow (no empty space)
    - "contain": Scale to fit within target, pad with background_color (no cropping)
    - "fill":    Stretch to exact dimensions (may distort)
    - "inside":  Scale down only if larger, maintain aspect ratio
    """
    img = Image.open(image_path).convert("RGBA")
    orig_w, orig_h = img.size
    target_ratio = width / height
    orig_ratio = orig_w / orig_h

    if fit == "cover":
        # Scale to fill, then crop
        if orig_ratio > target_ratio:
            # Image is wider — scale by height, crop width
            scale = height / orig_h
        else:
            # Image is taller — scale by width, crop height
            scale = width / orig_w
        
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Crop from gravity point
        gravity_offsets = {
            "center":       ((new_w - width) // 2, (new_h - height) // 2),
            "top_left":     (0, 0),
            "top":          ((new_w - width) // 2, 0),
            "top_right":    (new_w - width, 0),
            "left":         (0, (new_h - height) // 2),
            "right":        (new_w - width, (new_h - height) // 2),
            "bottom_left":  (0, new_h - height),
            "bottom":       ((new_w - width) // 2, new_h - height),
            "bottom_right": (new_w - width, new_h - height),
        }
        ox, oy = gravity_offsets.get(gravity, gravity_offsets["center"])
        img = img.crop((ox, oy, ox + width, oy + height))

    elif fit == "contain":
        # Scale to fit within bounds, pad remainder
        if orig_ratio > target_ratio:
            scale = width / orig_w
        else:
            scale = height / orig_h
        
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Create background and paste centered
        bg_color = _hex_to_rgba(background_color)
        canvas = Image.new("RGBA", (width, height), bg_color)
        offset = ((width - new_w) // 2, (height - new_h) // 2)
        canvas.paste(img, offset, img)
        img = canvas

    elif fit == "fill":
        img = img.resize((width, height), Image.LANCZOS)

    elif fit == "inside":
        if orig_w > width or orig_h > height:
            img.thumbnail((width, height), Image.LANCZOS)

    # Export
    output = io.BytesIO()
    if output_format == "jpeg":
        img = img.convert("RGB")
        img.save(output, format="JPEG", quality=quality)
        mime = "image/jpeg"
    elif output_format == "webp":
        img.save(output, format="WEBP", quality=quality)
        mime = "image/webp"
    else:
        img.save(output, format="PNG")
        mime = "image/png"

    return {
        "image_bytes": output.getvalue(),
        "mime_type": mime,
        "dimensions": {"width": img.width, "height": img.height},
    }


def _hex_to_rgba(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) + (255,)


registry.register(Tool(
    name="resize",
    description="Resize an image to exact pixel dimensions with smart cropping, padding, or stretching. Supports multiple fit modes: 'cover' fills the target and crops overflow, 'contain' fits within and pads, 'fill' stretches, 'inside' only shrinks. Use for adapting generated images to specific ad/social media sizes.",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Path to the source image."},
            "width": {"type": "integer", "description": "Target width in pixels."},
            "height": {"type": "integer", "description": "Target height in pixels."},
            "fit": {
                "type": "string",
                "enum": ["cover", "contain", "fill", "inside"],
                "description": "'cover' = fill & crop, 'contain' = fit & pad, 'fill' = stretch, 'inside' = shrink only.",
                "default": "cover"
            },
            "background_color": {
                "type": "string",
                "description": "Hex color for padding in 'contain' mode (e.g., '#FFFFFF').",
                "default": "#000000"
            },
            "gravity": {
                "type": "string",
                "enum": ["center", "top", "bottom", "left", "right", "top_left", "top_right", "bottom_left", "bottom_right"],
                "description": "Crop anchor point for 'cover' mode.",
                "default": "center"
            },
            "quality": {"type": "integer", "description": "Output quality 1-100 (for JPEG/WebP).", "default": 95},
            "output_format": {
                "type": "string",
                "enum": ["png", "jpeg", "webp"],
                "default": "png"
            }
        },
        "required": ["image_path", "width", "height"]
    },
    callable=resize,
    returns="Resized image as {image_bytes, mime_type, dimensions} dict.",
    tags=["post-processing"]
))
```

### Tool 6: `remove_background` — Background Removal

```python
# tools/remove_background.py
"""Remove background from an image using rembg (U2-Net based)."""

import io
from PIL import Image
from rembg import remove, new_session
from tools.registry import registry, Tool

# Pre-load model session for faster subsequent calls
_session = None

def _get_session():
    global _session
    if _session is None:
        _session = new_session("u2net")  # Options: u2net, u2netp (lighter), isnet-general-use
    return _session


async def remove_background(
    image_path: str,
    model: str = "u2net",
    alpha_matting: bool = False,
    alpha_matting_foreground_threshold: int = 240,
    alpha_matting_background_threshold: int = 10,
    post_process_mask: bool = True,
    background_color: str | None = None,
) -> dict:
    """
    Remove the background from an image, returning a transparent PNG.
    
    Use cases:
    - Extract a logo from a photo for compositing
    - Isolate a product from its background
    - Prepare overlays for the composite tool
    
    Optionally replace background with a solid color instead of transparency.
    """
    import asyncio

    session = _get_session() if model == "u2net" else new_session(model)

    with open(image_path, "rb") as f:
        input_bytes = f.read()

    # rembg is CPU-bound, run in thread
    output_bytes = await asyncio.to_thread(
        remove,
        input_bytes,
        session=session,
        alpha_matting=alpha_matting,
        alpha_matting_foreground_threshold=alpha_matting_foreground_threshold,
        alpha_matting_background_threshold=alpha_matting_background_threshold,
        post_process_mask=post_process_mask,
    )

    result = Image.open(io.BytesIO(output_bytes)).convert("RGBA")

    # Optionally replace transparency with solid color
    if background_color:
        h = background_color.lstrip("#")
        bg_rgba = tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) + (255,)
        bg = Image.new("RGBA", result.size, bg_rgba)
        bg.paste(result, (0, 0), result)
        result = bg

    buf = io.BytesIO()
    result.save(buf, format="PNG")

    return {
        "image_bytes": buf.getvalue(),
        "mime_type": "image/png",
        "dimensions": {"width": result.width, "height": result.height},
    }


registry.register(Tool(
    name="remove_background",
    description="Remove the background from an image, producing a transparent PNG. Uses AI-based segmentation (U2-Net). Ideal for isolating logos, products, or subjects before compositing them onto generated images. Optionally replace background with a solid color.",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the image to process."
            },
            "model": {
                "type": "string",
                "enum": ["u2net", "u2netp", "isnet-general-use"],
                "description": "'u2net' = best quality, 'u2netp' = faster/lighter, 'isnet-general-use' = good general purpose.",
                "default": "u2net"
            },
            "alpha_matting": {
                "type": "boolean",
                "description": "Enable alpha matting for finer edge detail (hair, fur, etc.). Slower but higher quality edges.",
                "default": false
            },
            "post_process_mask": {
                "type": "boolean",
                "description": "Clean up the segmentation mask to reduce artifacts.",
                "default": true
            },
            "background_color": {
                "type": "string",
                "description": "Optional hex color to replace background with instead of transparency (e.g., '#FFFFFF'). Null for transparent.",
                "default": null
            }
        },
        "required": ["image_path"]
    },
    callable=remove_background,
    returns="Image with background removed as {image_bytes, mime_type, dimensions} dict.",
    tags=["editing"]
))
```

### Tool Summary & Agent Access

```
┌─────────────────────────────────────────────────────────────────────┐
│  TOOL REGISTRY                                                      │
├──────────────────────┬──────────┬───────────────────────────────────┤
│  Tool Name           │ Tag      │ Backend                           │
├──────────────────────┼──────────┼───────────────────────────────────┤
│  generate_image      │ gen      │ Gemini Imagen 3                   │
│  generate_with_ref   │ gen      │ Gemini 2.0 Flash (multimodal)     │
│  composite           │ post     │ Pillow (local)                    │
│  outpaint            │ edit     │ Gemini 2.0 Flash + Pillow         │
│  resize              │ post     │ Pillow (local)                    │
│  remove_background   │ edit     │ rembg / U2-Net (local)            │
└──────────────────────┴──────────┴───────────────────────────────────┘

The orchestrator exposes ALL tools to the Gemini function-calling agent:

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=conversation,
        config={
            "tools": [{"function_declarations": registry.to_gemini_function_declarations()}],
        },
    )

This lets the LLM autonomously decide the tool chain:
  "Make a LinkedIn banner with our logo" →
    1. generate_image(prompt=..., aspect_ratio="16:9")
    2. remove_background(image_path=logo.png)
    3. composite(base=step1, overlay=step2, position=top_left, overlay_scale=0.15)
    4. resize(width=1584, height=396)
```

### Additional Backend Dependencies

```bash
# Add to requirements
pip install Pillow rembg onnxruntime
# rembg will auto-download the U2-Net model on first use (~170MB)
```

---

## FastAPI Endpoints (`routers/`)

### Brand Management (`routers/brands.py`)

```
GET    /api/brands                    → List all brands
POST   /api/brands                    → Create brand
GET    /api/brands/{id}               → Get brand with rules + assets
PUT    /api/brands/{id}               → Update brand
DELETE /api/brands/{id}               → Delete brand

POST   /api/brands/{id}/rules         → Add rule
PUT    /api/brands/{id}/rules/{rid}   → Update rule
DELETE /api/brands/{id}/rules/{rid}   → Delete rule

POST   /api/brands/{id}/assets        → Upload asset (multipart)
DELETE /api/brands/{id}/assets/{aid}   → Delete asset
```

### Generation (`routers/generations.py`)

```
POST   /api/generate                  → Start generation job (returns job_id)
       Body: { brand_id, prompt, num_variations?, max_iterations?, score_threshold? }

GET    /api/generate/{job_id}/stream  → SSE endpoint for live progress
GET    /api/generate/{job_id}         → Get job result with all images + scores
GET    /api/generate/{job_id}/images  → List generated images for job
POST   /api/generate/{job_id}/select  → Manually override winner selection

GET    /api/history                   → List past generation jobs
GET    /api/history?brand_id=x        → Filter by brand
```

### SSE Progress Events

The `/stream` endpoint pushes these events:

```
event: status
data: {"stage": "engineering", "iteration": 1}

event: prompts
data: {"iteration": 1, "prompts": ["detailed prompt 1...", "detailed prompt 2..."]}

event: status
data: {"stage": "generating", "iteration": 1}

event: status
data: {"stage": "judging", "iteration": 1}

event: judged
data: {"iteration": 1, "results": [{"variation": 1, "score": 82, "violations": [...], "path": "/generated/..."}]}

event: complete
data: {"winner": {...}, "iterations_used": 2}
```

---

## Frontend Pages

### 1. Brand Manager (`BrandManager.jsx`)

Core features:
- **Brand list** with cards showing name, color palette preview, rule count
- **Brand editor** drawer/modal:
  - Name, description fields
  - **Color palette editor** — click swatches to edit, add/remove colors
  - **Font selector** — heading + body font pickers
  - **Rule editor** — table with category dropdown, severity badge, editable rule text, + add/delete
  - **Asset uploader** — drag-and-drop zone, shows thumbnails of uploaded logos/assets with type tags

### 2. Generation Studio (`GenerationStudio.jsx`)

Core features:
- **Brand selector** dropdown at top
- **Prompt input** — textarea with brand context hints
- **Config panel** — sliders for num_variations (1-8), max_iterations (1-5), score_threshold (50-95)
- **Live generation view** (connected via SSE):
  - Progress stepper: Engineering → Generating → Judging → Complete
  - Shows engineered prompts as they come in
  - Image grid fills in as images generate
  - Score badges overlay on each image after judging
  - Rule violation chips (red for critical, yellow for warning)
  - Iteration indicator if retrying
- **Winner panel** — highlighted best image with full score breakdown
- **Manual override** — click any image to select it as winner instead

### 3. History (`History.jsx`)

- Filterable list of past generation jobs
- Click to expand: shows all iterations, all variations, scores, the winner
- Re-run button to try again with same prompt

---

## Key Implementation Details

### Brand Context Assembly (`agents/brand_context.py`)

```python
async def load_brand_context(brand_id: str, db) -> dict:
    """Assembles the full brand context dict used by all agents."""
    brand = await db.get_brand(brand_id)
    rules = await db.get_brand_rules(brand_id)
    assets = await db.get_brand_assets(brand_id)

    return {
        "brand_name": brand.name,
        "description": brand.description,
        "colors": json.loads(brand.colors_json),
        "fonts": json.loads(brand.fonts_json),
        "rules": [
            {
                "id": r.id,
                "category": r.category,
                "severity": r.severity,
                "rule": r.rule_text,
                "enforcement_prompt": r.enforcement_prompt,
            }
            for r in rules
        ],
        "assets": [
            {
                "id": a.id,
                "type": a.asset_type,
                "name": a.name,
                "description": a.description,
                "file_path": a.file_path,
            }
            for a in assets
        ],
        "metadata": json.loads(brand.metadata_json),
    }
```

### Async Parallel Generation Pattern

The key insight: fire all image generations concurrently, then judge concurrently too. This cuts wall-clock time dramatically vs sequential:

```python
# Sequential: N * (gen_time + judge_time) ≈ N * 25s = 100s for 4 images
# Parallel:   max(gen_time) + max(judge_time) ≈ 25s for 4 images

results = await asyncio.gather(
    *[generate_one(p, i) for i, p in enumerate(prompts)],
    return_exceptions=True,  # Don't fail all if one fails
)
```

### Brand Rule Severity Logic

- **Critical**: Must pass. If ANY critical rule is violated, the judge should score below threshold and trigger a retry.
- **Warning**: Should pass. Violations reduce score but don't force retry.
- **Suggestion**: Nice to have. Minor score impact, informational.

The judge prompt explicitly weights these:
```
- A critical violation should reduce the score by 20-40 points
- A warning violation should reduce the score by 5-15 points  
- A suggestion violation should reduce the score by 1-5 points
- An image with zero critical violations starts at 80+ baseline
```

---

## Environment Variables

```env
GEMINI_API_KEY=your-key-here
DATABASE_URL=sqlite:///./brand_agent.db
GENERATED_IMAGES_DIR=./generated
UPLOADED_ASSETS_DIR=./uploads
MAX_PARALLEL_GENERATIONS=8
DEFAULT_NUM_VARIATIONS=4
DEFAULT_MAX_ITERATIONS=3
DEFAULT_SCORE_THRESHOLD=75
```

---

## Getting Started (Claude Code)

```bash
# 1. Scaffold
mkdir brand-image-agent && cd brand-image-agent
mkdir -p backend/{agents,services,routers,database,schemas,tools} frontend/src/{pages,components,hooks} generated uploads

# 2. Backend deps
cd backend
pip install fastapi uvicorn sqlalchemy aiosqlite google-genai python-multipart sse-starlette Pillow rembg onnxruntime

# 3. Frontend deps
cd ../frontend
npm create vite@latest . -- --template react
npm install axios tailwindcss @headlessui/react lucide-react

# 4. Build order (recommended):
#    a. database/models.py + session.py  → Get DB working
#    b. services/gemini.py              → Test Gemini calls
#    c. agents/brand_context.py         → Brand loading
#    d. agents/prompt_engineer.py       → Prompt generation
#    e. agents/judge.py                 → Image judging
#    f. agents/orchestrator.py          → Wire the loop
#    g. routers/brands.py              → Brand CRUD API
#    h. routers/generations.py          → Generation + SSE API
#    i. Frontend pages                  → UI last
```

---

## Extension Ideas (V2+)

- **Composite images**: Overlay actual logo PNGs onto generated images using Pillow post-processing
- **A/B testing**: Generate for multiple audiences, track which performs better
- **Template system**: Save winning prompt structures as reusable templates per brand
- **Multi-model**: Add DALL-E / Flux as alternative backends, let the judge compare across models
- **Brand style transfer**: Fine-tune or use reference images to get closer to a specific aesthetic
- **Approval workflow**: Add a human-in-the-loop step before finalizing
- **Batch generation**: Queue up multiple assets (banner, social card, icon) in one run
