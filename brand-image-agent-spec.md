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
mkdir -p backend/{agents,services,routers,database,schemas} frontend/src/{pages,components,hooks} generated uploads

# 2. Backend deps
cd backend
pip install fastapi uvicorn sqlalchemy aiosqlite google-genai python-multipart sse-starlette

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
