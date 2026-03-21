# Brand Image Generation Agent — ADK-Only Spec

## Overview

An agentic framework that generates brand-compliant images using Gemini, with a SQLite brand asset database, rule enforcement, and async parallel generation. The system uses an LLM-powered loop: **prompt engineering → parallel image generation → judging → retry if needed**.

Built entirely on Google ADK primitives.

---

## Tech Stack

| Layer | Tech | Notes |
|-------|------|-------|
| Agent Framework | Google ADK (`google-adk`) | SequentialAgent, ParallelAgent, LoopAgent, custom tools |
| Database | SQLite via SQLAlchemy | Brand assets, rules, generation history |
| Image Gen | Nano Banana 2 (`gemini-3.1-flash-image-preview`) | Via `google-genai` SDK — single `generateContent` API for gen + edit |
| LLM Agent | Gemini 3 Flash (`gemini-3-flash-preview`) | Prompt engineering + judging agents (via ADK LlmAgent) |
| Image Processing | Pillow, rembg | Compositing, resize, background removal (local, no API) |

---

## Project Structure

```
brand-image-agent/
├── agents/                            # ADK agent definitions
│   ├── __init__.py
│   ├── brand_image_agent/             # Root ADK agent package
│   │   ├── __init__.py                # Exports root_agent
│   │   ├── agent.py                   # Root SequentialAgent definition
│   │   ├── sub_agents/
│   │   │   ├── prompt_engineer.py     # LlmAgent: user request → N image prompts
│   │   │   ├── image_generator.py     # Custom agent: wraps asyncio.gather for N generations
│   │   │   └── judge_agent.py         # LlmAgent: scores images, decides retry vs accept
│   │   └── tools/
│   │       ├── generate_image.py      # Tool: text-to-image via Nano Banana 2
│   │       ├── generate_with_ref.py   # Tool: reference-guided generation
│   │       ├── edit_image.py          # Tool: conversational image editing
│   │       ├── outpaint.py            # Tool: extend image canvas
│   │       ├── composite.py           # Tool: layer images (Pillow)
│   │       ├── resize.py              # Tool: resize/crop/pad (Pillow)
│   │       ├── remove_background.py   # Tool: bg removal (rembg)
│   │       ├── render_text.py         # Tool: exact typography with real fonts + brand colors
│   │       └── brand_db.py            # Utility: load_brand_context() + query helpers
├── database/
│   ├── models.py                      # SQLAlchemy ORM models
│   ├── schema.sql                     # Raw DDL for reference
│   ├── seed.py                        # Seed data for demo brands
│   └── session.py                     # DB session factory
├── generated/                         # Output images
├── uploads/                           # Uploaded brand assets
├── .env
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
    colors_json TEXT NOT NULL DEFAULT '{}',
    -- Colors map: role → hex. The role names are used by render_text tool.
    -- Example: {
    --   "primary": "#0F62FE",
    --   "secondary": "#6929C4",
    --   "accent": "#08BDBA",
    --   "background": "#161616",
    --   "text_primary": "#F4F4F4",
    --   "text_secondary": "#C6C6C6",
    --   "text_on_primary": "#FFFFFF",
    --   "error": "#DA1E28"
    -- }
    fonts_json TEXT NOT NULL DEFAULT '{}',
    -- Font map: role → asset_id (references brand_assets with asset_type='font').
    -- Example: {
    --   "heading": "asset_abc123",
    --   "body": "asset_def456",
    --   "accent": "asset_ghi789"
    -- }
    -- The render_text tool resolves asset_id → file_path at runtime.
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Brand Rules (the core of rule enforcement)
-- Rules can be brand-wide (asset_id IS NULL) or scoped to a specific asset.
-- When the agent uses an asset, it loads both the brand-wide rules AND
-- that asset's specific rules into context.
CREATE TABLE brand_rules (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    brand_id TEXT NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    asset_id TEXT REFERENCES brand_assets(id) ON DELETE CASCADE,
    -- NULL = brand-wide rule, set = rule applies only to this asset
    category TEXT NOT NULL,          -- 'color' | 'composition' | 'typography' | 'style' | 'tone' | 'content' | 'layout' | 'spacing' | 'sizing' | 'placement' | 'pairing'
    severity TEXT NOT NULL DEFAULT 'warning',  -- 'critical' | 'warning' | 'suggestion'
    rule_text TEXT NOT NULL,          -- Human-readable rule description
    enforcement_prompt TEXT,          -- Optional: specific LLM prompt to check this rule
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Examples of brand-wide rules (asset_id IS NULL):
--   category='color',    "Primary blue (#0F62FE) must be dominant in hero images"
--   category='style',    "Prefer geometric, clean-line illustrations over photorealistic"
--   category='tone',     "Imagery should feel technical, precise, forward-looking"
--
-- Examples of asset-specific rules (asset_id set):
--   Logo rules:
--     category='spacing',   "Minimum 15% clear space around logo on all sides"
--     category='placement', "Logo must be in top-left or center, never bottom-right"
--     category='sizing',    "Logo must be at least 10% of image width, never exceed 25%"
--     category='pairing',   "Only use white logo variant on dark backgrounds"
--     category='style',     "Never place logo over busy or textured areas"
--   Font rules:
--     category='sizing',    "Minimum font size 24px for headings, 14px for body"
--     category='pairing',   "Only pair with text_primary or text_on_primary colors"
--     category='typography',"Use only for headings, never for body text"
--     category='spacing',   "Line height must be at least 1.4x for body text"
--   Photo/pattern rules:
--     category='color',     "Always apply brand blue overlay at 20% opacity"
--     category='composition',"Never crop below the subject's shoulders"

-- Brand Assets (logos, icons, patterns, fonts, etc.)
CREATE TABLE brand_assets (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    brand_id TEXT NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL,         -- 'logo' | 'icon' | 'pattern' | 'photo' | 'illustration' | 'font'
    name TEXT NOT NULL,               -- e.g. "IBM Plex Sans Bold", "Primary Logo White"
    description TEXT,                 -- Usage notes: "Use for headings on dark backgrounds"
    file_path TEXT NOT NULL,          -- Path to uploaded file (.ttf, .otf, .png, etc.)
    mime_type TEXT,                   -- 'font/ttf', 'font/otf', 'image/png', etc.
    metadata_json TEXT DEFAULT '{}',
    -- For fonts: {"weight": "bold", "style": "italic", "fallback": "Arial"}
    -- For images: {"width": 1200, "height": 630, "variants": ["dark", "light"]}
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
CREATE INDEX idx_rules_asset ON brand_rules(asset_id);
CREATE INDEX idx_rules_brand_wide ON brand_rules(brand_id) WHERE asset_id IS NULL;
CREATE INDEX idx_assets_brand ON brand_assets(brand_id);
CREATE INDEX idx_jobs_brand ON generation_jobs(brand_id);
CREATE INDEX idx_images_job ON generated_images(job_id);
```

---

## Agent Architecture (Google ADK)

### Overview

The entire orchestration is built with Google ADK primitives. No custom `asyncio.gather` or manual retry loops — ADK's `LoopAgent`, `ParallelAgent`, and `SequentialAgent` handle it.

```
root_agent (SequentialAgent)
 │
 ├── 1. refinement_loop         (LoopAgent, max_iterations=3)
 │   │
 │   ├── 1a. prompt_engineer    (LlmAgent, Gemini 3 Flash)
 │   │      Reads state["brand_context"] + state["user_prompt"]
 │   │      + state["previous_feedback"] (if retry)
 │   │      Outputs state["engineered_prompts"] (JSON array of N prompts)
 │   │      NOTE: Prompts should tell NB2 to leave clean space for text
 │   │      rather than generating text in the image (render_text handles that)
 │   │
 │   ├── 1b. parallel_generator (Custom BaseAgent wrapping asyncio.gather)
 │   │      Reads prompts, fires N parallel Nano Banana 2 calls
 │   │      Writes state["generated_images"]
 │   │
 │   └── 1c. judge              (LlmAgent, Gemini 3 Flash)
 │          Reads state["generated_images"] + state["brand_context"]
 │          Scores each 0-100, lists violations
 │          Outputs state["judge_results"]
 │          If best score >= threshold → escalate=True (breaks loop)
 │          Else → writes state["previous_feedback"] for retry
 │
 └── 2. post_processor          (LlmAgent with render_text/composite/resize/outpaint tools)
        Reads state["winner_image"] + state["brand_context"]
        Adds text using real brand fonts + colors (render_text)
        Overlays logo (composite), resizes to target (resize), etc.
        Has full brand context so it picks the right font_role + color_role
```

### ADK Agent Definitions

#### Root Agent (`agent.py`)

```python
from google.adk.agents import SequentialAgent, LoopAgent

refinement_loop = LoopAgent(
    name="RefinementLoop",
    sub_agents=[prompt_engineer, parallel_generator, judge_agent],
    max_iterations=3,
)

root_agent = SequentialAgent(
    name="BrandImageAgent",
    sub_agents=[refinement_loop, post_processor],
    description="Generates brand-compliant images using iterative refinement.",
)
```

#### Prompt Engineer — `LlmAgent`

- **Model:** `gemini-3-flash-preview`
- **Reads:** `state["brand_context"]`, `state["user_prompt"]`, `state["previous_feedback"]`
- **Writes:** `state["engineered_prompts"]` (JSON array of N prompt strings)
- **Instruction:** Generate N distinct, brand-compliant image prompts with explicit hex colors, composition details. On retry, fix issues from previous feedback. **Critical: prompts should instruct NB2 to leave clean negative space where text will be placed** (e.g., "leave the upper third clean for headline text") — the `render_text` tool handles actual typography in post-processing. NB2 should NOT be asked to generate text in the image.

#### Judge — `LlmAgent`

- **Model:** `gemini-3-flash-preview`
- **Reads:** `state["generated_images"]`, `state["brand_context"]`
- **Writes:** `state["judge_results"]` — `{results: [{variation, score, violations, strengths, improvements}]}`
- **Scoring weights:** Critical violation: -20 to -40 pts. Warning: -5 to -15. Suggestion: -1 to -5. Zero critical violations baseline: 80+.
- **Post-scoring logic (in `after_agent_callback` or output handler):** Finds the best score. If `score >= threshold`, sets `escalate=True` to break the `LoopAgent` and writes `state["winner_image"]`. Otherwise, writes `state["previous_feedback"]` with critical violations and improvement suggestions for the next loop iteration.

#### Parallel Image Generator — Custom `BaseAgent`

Reads `state["engineered_prompts"]`, fires N parallel Nano Banana 2 `generateContent` calls via `asyncio.gather`, writes results to `state["generated_images"]`.

> **Why Custom instead of ADK ParallelAgent?** ADK's `ParallelAgent` needs a static list of sub-agents defined at init time. Since N (number of variations) is dynamic per-request, a Custom BaseAgent with `asyncio.gather` inside is cleaner.

### State Flow

```
state["user_prompt"]          ← Set when session starts
state["brand_id"]             ← Set when session starts
state["brand_context"]        ← Set at init via load_brand_context(brand_id)
state["score_threshold"]      ← Set at init (default 75)
state["aspect_ratio"]         ← Set at init (default "1:1")
state["resolution"]           ← Set at init (default "1K")
state["num_variations"]       ← Set at init (default 4)
state["engineered_prompts"]   ← Written by prompt_engineer
state["generated_images"]     ← Written by parallel_generator
state["judge_results"]        ← Written by judge_agent
state["previous_feedback"]    ← Written by judge_agent (for retry)
state["best_result"]          ← Written by judge_agent
state["winner_image"]         ← Written by judge_agent when threshold met
```

### Running the Agent

```python
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from database.session import load_brand_context

runner = Runner(
    agent=root_agent,
    app_name="brand_image_agent",
    session_service=InMemorySessionService(),
)

session = await runner.session_service.create_session(
    app_name="brand_image_agent", user_id="user_123"
)
session.state.update({
    "user_prompt": "Create a hero banner for our Q4 product launch",
    "brand_id": "brand_001",
    "brand_context": load_brand_context("brand_001"),  # plain function, not an agent
    "score_threshold": 75,
    "aspect_ratio": "16:9",
    "resolution": "2K",
    "num_variations": 4,
})

async for event in runner.run_async(
    user_id="user_123", session_id=session.id, new_message="Go"
):
    print(f"[{event.author}] {event}")

# Result: session.state["winner_image"]
```

### ADK Dev UI

ADK ships with a built-in dev UI (`adk web`) for debugging agent flows — you can inspect state at each step, see which sub-agents fired, and trace the full execution.

---

## Nano Banana 2 — API Reference

Single unified API — `generateContent`. No separate image endpoint.

```
Model:          gemini-3.1-flash-image-preview
Input:          Text + up to 14 reference images
Output:         Interleaved text + image parts (inline_data with base64 PNG)
Aspect Ratios:  1:1, 1:4, 1:8, 2:3, 3:2, 3:4, 4:1, 4:3, 4:5, 5:4, 8:1, 9:16, 16:9, 21:9
Resolutions:    512px, 1K (default), 2K, 4K  (uppercase K required)
Thinking:       Always on. Levels: "minimal" (default), "high"
Search:         Google Search + Image Search grounding
Multi-turn:     Via chat with thought signatures (SDK handles automatically)
```

All image tools (`generate_image`, `edit_image`, `outpaint`, `generate_with_reference`) use `google.genai.Client().models.generate_content()` with `response_modalities=["IMAGE"]` and `image_config=ImageConfig(aspect_ratio=..., image_size=...)`. Skip `part.thought == True` parts in the response to get only the final image.

---

## Tool Registry

All tools are registered centrally so the orchestrator (or Gemini function calling) can discover and invoke them. Every tool that touches Nano Banana 2 uses `generateContent` — there is no separate image generation endpoint.

### Registry Pattern (`tools/registry.py`)

Each tool is a `Tool` dataclass with `name`, `description`, `parameters` (JSON Schema), `callable` (async function), `returns`, and `tags`. The registry exposes `to_gemini_function_declarations()` to export all tool schemas for Gemini function calling, and `invoke(name, **kwargs)` to call tools dynamically.

### Tool Definitions

#### `generate_image` — Text-to-Image

| | |
|---|---|
| **Backend** | Nano Banana 2 `generateContent` with `response_modalities=["IMAGE"]` |
| **Tag** | `generation` |

**Parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `prompt` | string | *required* | Detailed prompt with style, colors, composition |
| `aspect_ratio` | enum | `"1:1"` | `1:1, 1:4, 1:8, 2:3, 3:2, 3:4, 4:1, 4:3, 4:5, 5:4, 8:1, 9:16, 16:9, 21:9` |
| `resolution` | enum | `"1K"` | `512px, 1K, 2K, 4K` — uppercase K required |
| `thinking_level` | enum | `"minimal"` | `minimal, high` — higher = better quality, more latency |

**Key implementation note:** Set `image_config=types.ImageConfig(aspect_ratio=..., image_size=...)` in the config. Skip thought parts in response (`part.thought == True`). Extract `part.inline_data.data` for image bytes.

---

#### `generate_with_reference` — Reference-Guided Generation

| | |
|---|---|
| **Backend** | Nano Banana 2 `generateContent` with images in `contents` |
| **Tag** | `generation` |

**Parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `prompt` | string | *required* | What to generate |
| `reference_images` | string[] | *required* | File paths, max 14 (10 object + 4 character) |
| `reference_mode` | enum | `"style"` | `style, composition, subject, brand` |
| `aspect_ratio` | enum | `"1:1"` | Same options as generate_image |
| `resolution` | enum | `"1K"` | Same options |

**Key implementation note:** Pass `PIL.Image.open()` objects directly in the `contents` list alongside the text prompt — the SDK handles serialization. Prepend mode-specific instructions to the prompt (e.g. "Match the visual style of the reference images").

---

#### `edit_image` — Conversational Image Editing

| | |
|---|---|
| **Backend** | Nano Banana 2 `generateContent` with image + text in `contents` |
| **Tag** | `editing` |

**Parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `image_path` | string | *required* | Image to edit |
| `edit_prompt` | string | *required* | Natural language edit instruction |
| `aspect_ratio` | enum | `null` | Optionally change AR (useful for outpainting) |
| `resolution` | enum | `"1K"` | Output resolution |

**Key implementation note:** Same API as generation — just include the source image in `contents`. Use `response_modalities=["TEXT", "IMAGE"]` to get both feedback text and the edited image. For multi-turn editing, use the SDK's `client.chats.create()` which handles thought signatures automatically.

---

#### `outpaint` — Extend Image Canvas

| | |
|---|---|
| **Backend** | Nano Banana 2 (native AR change) or Pillow pad + NB2 fill |
| **Tag** | `editing` |

**Parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `image_path` | string | *required* | Source image |
| `target_aspect_ratio` | enum | `"16:9"` | All NB2 aspect ratios supported |
| `fill_prompt` | string | `""` | How to fill extended regions |
| `resolution` | enum | `"2K"` | Output resolution |
| `strategy` | enum | `"native"` | `native` = let NB2 handle via AR change; `pad_and_fill` = Pillow canvas pad then NB2 fill |

**Key implementation note:** The `native` strategy is simplest — just call `edit_image` with the source image, a prompt like "Extend this image seamlessly", and the new `aspect_ratio`. The `pad_and_fill` strategy gives precise pixel control: create a white-padded canvas with Pillow, then pass it to NB2 with "Fill the white borders matching the original style".

---

#### `composite` — Layer Images Together

| | |
|---|---|
| **Backend** | Pillow (local, no API call) |
| **Tag** | `post-processing` |

**Parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `base_image_path` | string | *required* | Background image |
| `overlay_image_path` | string | *required* | Overlay (e.g. logo PNG with transparency) |
| `position` | enum | `"center"` | 9-point: `top_left, top_center, top_right, center_left, center, center_right, bottom_left, bottom_center, bottom_right` |
| `overlay_scale` | float | `0.2` | Scale relative to base width (0.1 = 10%) |
| `opacity` | float | `1.0` | 0.0–1.0 |
| `padding` | int | `20` | Edge padding in pixels |
| `x_offset` | int | `0` | Fine-tune horizontal position |
| `y_offset` | int | `0` | Fine-tune vertical position |

**Key implementation note:** Pure Pillow. Open both as RGBA, resize overlay proportionally, apply opacity via alpha channel, paste with alpha mask. No API call needed.

---

#### `resize` — Resize / Crop / Pad

| | |
|---|---|
| **Backend** | Pillow (local, no API call) |
| **Tag** | `post-processing` |

**Parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `image_path` | string | *required* | Source image |
| `width` | int | *required* | Target width in pixels |
| `height` | int | *required* | Target height in pixels |
| `fit` | enum | `"cover"` | `cover` = fill + crop, `contain` = fit + pad, `fill` = stretch |
| `background_color` | string | `"#000000"` | Pad color for `contain` mode |
| `gravity` | enum | `"center"` | Crop anchor for `cover` mode |
| `output_format` | enum | `"png"` | `png, jpeg` |

---

#### `remove_background` — Background Removal

| | |
|---|---|
| **Backend** | rembg / U2-Net (local inference, no API call) |
| **Tag** | `editing` |

**Parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `image_path` | string | *required* | Image to process |
| `alpha_matting` | bool | `false` | Finer edges for hair/fur — slower |
| `background_color` | string | `null` | Replace bg with hex color instead of transparency |

**Key implementation note:** Use `rembg.remove()` with `new_session("u2net")`. Run in `asyncio.to_thread()` since it's CPU-bound. Model auto-downloads on first use (~170MB).

---

#### `render_text` — Exact Typography with Brand Fonts & Colors

| | |
|---|---|
| **Backend** | Pillow `ImageDraw` + `ImageFont` (local, no API call) |
| **Tag** | `post-processing` |

This is the key tool for brand-accurate typography. Nano Banana 2 can't use actual font files — it approximates fonts from text descriptions. This tool renders pixel-perfect text using the real `.ttf`/`.otf` files stored as brand assets, in the exact brand colors.

**Parameters:**

| Param | Type | Default | Notes |
|---|---|---|---|
| `image_path` | string | *required* | Base image to render text onto |
| `text` | string | *required* | The text to render |
| `font_role` | enum | `"heading"` | Which brand font to use: `heading, body, accent`. Resolved from `state["brand_context"]["fonts"]` → asset_id → file_path |
| `color_role` | enum | `"text_primary"` | Which brand color to use: `primary, secondary, accent, text_primary, text_secondary, text_on_primary`, etc. Resolved from `state["brand_context"]["colors"]` → hex value |
| `color_hex` | string | `null` | Override: use a specific hex color instead of a role |
| `font_size` | int | `48` | Font size in pixels |
| `position` | enum | `"center"` | 9-point: `top_left, top_center, top_right, center_left, center, center_right, bottom_left, bottom_center, bottom_right` |
| `x_offset` | int | `0` | Fine-tune horizontal |
| `y_offset` | int | `0` | Fine-tune vertical |
| `padding` | int | `40` | Edge padding in pixels |
| `max_width` | int | `null` | Max text width before wrapping (pixels). Null = no wrap |
| `line_spacing` | float | `1.3` | Line height multiplier for wrapped text |
| `alignment` | enum | `"center"` | `left, center, right` — text alignment for multi-line |
| `stroke_width` | int | `0` | Text outline thickness (0 = no outline) |
| `stroke_color_role` | string | `null` | Brand color role for stroke. Useful for readability on busy backgrounds |
| `shadow` | bool | `false` | Add drop shadow for readability |

**Key implementation notes:**

- Resolves `font_role` → looks up `state["brand_context"]["fonts"][font_role]` to get an `asset_id`, then queries the DB for the asset's `file_path` to load the `.ttf`/`.otf` via `PIL.ImageFont.truetype(file_path, font_size)`.
- Resolves `color_role` → looks up `state["brand_context"]["colors"][color_role]` to get the hex value.
- For text wrapping, use `ImageDraw.textbbox()` to measure text width and split into lines when exceeding `max_width`.
- The agent (post-processor LlmAgent) decides which font role, color role, size, and position to use based on the brand rules and the type of content being generated.

**Example — the agent decides the typography:**

The post-processor LlmAgent has access to the full brand context. When it needs to add a headline, it reasons: "This is a heading on a dark background → use `font_role='heading'`, `color_role='text_on_primary'`, `font_size=72`." It then calls `render_text` with those parameters. The tool handles the actual font file loading and color resolution.

---

### Tool Summary

```
┌──────────────────────────┬──────────┬─────────────────────────────────────────┐
│  Tool                    │ Tag      │ Backend                                 │
├──────────────────────────┼──────────┼─────────────────────────────────────────┤
│  generate_image          │ gen      │ Nano Banana 2 (generateContent)         │
│  generate_with_reference │ gen      │ Nano Banana 2 (generateContent + imgs)  │
│  edit_image              │ edit     │ Nano Banana 2 (generateContent + img)   │
│  outpaint                │ edit     │ Nano Banana 2 (aspect ratio change)     │
│  composite               │ post     │ Pillow (local, no API)                  │
│  resize                  │ post     │ Pillow (local, no API)                  │
│  remove_background       │ edit     │ rembg / U2-Net (local, no API)          │
│  render_text             │ post     │ Pillow + brand fonts/colors (local)     │
└──────────────────────────┴──────────┴─────────────────────────────────────────┘

Example agent tool chain for "Make a LinkedIn banner with our logo and headline":
  1. generate_image(prompt="abstract tech background...", aspect_ratio="21:9", resolution="2K")
  2. render_text(image=step1, text="Q4 PRODUCT LAUNCH", font_role="heading", color_role="text_on_primary", font_size=72, position="center")
  3. render_text(image=step2, text="Innovation at scale", font_role="body", color_role="text_secondary", font_size=32, position="bottom_center")
  4. remove_background(image_path=logo.png)
  5. composite(base=step3, overlay=step4, position="top_left", overlay_scale=0.12)
  6. resize(width=1584, height=396, fit="cover")
```

### Dependencies

```bash
pip install google-adk google-genai sqlalchemy aiosqlite Pillow rembg onnxruntime
# rembg auto-downloads U2-Net model on first use (~170MB)
```

---

## Key Implementation Details

### Brand Context Assembly

The `load_brand_context()` utility function queries SQLite and returns a structured dict that gets set on `state["brand_context"]` before the agent runs. Asset-specific rules are nested under each asset so tools can access them when using that asset:

```python
state["brand_context"] = {
    "brand_name": "Meridian Tech",
    "description": "Modern SaaS company...",
    "colors": {
        "primary": "#0F62FE",
        "secondary": "#6929C4",
        "text_primary": "#F4F4F4",
        "text_on_primary": "#FFFFFF",
        # ...
    },
    "fonts": {
        "heading": "asset_abc123",   # → resolves to IBM Plex Sans Bold .ttf
        "body": "asset_def456",
    },
    "rules": [
        # Brand-wide rules only (asset_id IS NULL)
        {"id": "r1", "category": "color", "severity": "critical",
         "rule": "Primary blue must be dominant in hero images"},
        # ...
    ],
    "assets": [
        {
            "id": "asset_abc123",
            "type": "font",
            "name": "IBM Plex Sans Bold",
            "file_path": "/uploads/fonts/ibm-plex-sans-bold.ttf",
            "metadata": {"weight": "bold", "fallback": "Arial"},
            "rules": [
                # Asset-specific rules (asset_id = this asset)
                {"id": "r10", "category": "sizing", "severity": "critical",
                 "rule": "Minimum font size 24px for headings"},
                {"id": "r11", "category": "pairing", "severity": "warning",
                 "rule": "Only pair with text_primary or text_on_primary colors"},
            ]
        },
        {
            "id": "asset_logo1",
            "type": "logo",
            "name": "Primary Logo White",
            "file_path": "/uploads/logos/meridian-white.png",
            "metadata": {"width": 1200, "variants": ["dark"]},
            "rules": [
                {"id": "r20", "category": "spacing", "severity": "critical",
                 "rule": "Minimum 15% clear space around logo"},
                {"id": "r21", "category": "placement", "severity": "critical",
                 "rule": "Top-left or center only, never bottom-right"},
                {"id": "r22", "category": "pairing", "severity": "warning",
                 "rule": "Only use on dark backgrounds"},
            ]
        },
    ],
}
```

The tools (`render_text`, `composite`) read the relevant asset's `rules` array and enforce them. For example, `composite` checks the logo's placement and spacing rules before positioning. The judge agent also receives the full context including asset rules so it can score violations.

### Brand Rule Severity Logic

- **Critical**: Must pass. If ANY critical rule is violated, the judge should score below threshold and trigger a retry.
- **Warning**: Should pass. Violations reduce score but don't force retry.
- **Suggestion**: Nice to have. Minor score impact, informational.

---

## Environment Variables

```env
GOOGLE_GENAI_API_KEY=your-key-here
DATABASE_URL=sqlite:///./brand_agent.db
GENERATED_IMAGES_DIR=./generated
UPLOADED_ASSETS_DIR=./uploads
DEFAULT_NUM_VARIATIONS=4
DEFAULT_MAX_ITERATIONS=3
DEFAULT_SCORE_THRESHOLD=75
```

---

## Getting Started

```bash
# 1. Scaffold
mkdir brand-image-agent && cd brand-image-agent
mkdir -p agents/brand_image_agent/{sub_agents,tools} database generated uploads

# 2. Install deps
pip install google-adk google-genai sqlalchemy aiosqlite Pillow rembg onnxruntime

# 3. Build order (recommended):
#    a. database/models.py + session.py       → Get SQLite working
#    b. agents/tools/generate_image.py        → Test Nano Banana 2 calls
#    c. agents/tools/brand_db.py              → load_brand_context() utility
#    d. agents/sub_agents/prompt_engineer.py  → LlmAgent
#    e. agents/sub_agents/judge_agent.py      → LlmAgent + threshold logic
#    f. agents/sub_agents/image_generator.py  → Custom BaseAgent (parallel gen)
#    g. agents/agent.py                       → Wire SequentialAgent + LoopAgent
#    h. Test with: adk web                    → ADK dev UI

# 4. Test with ADK dev UI
adk web
```

---

## Extension Ideas (V2+)

- **A/B testing**: Generate for multiple audiences using ParallelAgent, track which performs better
- **Template system**: Save winning prompt structures as reusable templates per brand
- **Multi-model**: Add DALL-E / Flux as alternative tool backends, let the judge compare across models
- **Approval workflow**: Add a human-in-the-loop step using ADK's tool confirmation flow (HITL)
- **Batch generation**: Use ADK's SequentialAgent to queue up multiple assets (banner, social card, icon) in one run
- **A2A protocol**: Expose the agent as an A2A-compatible service for integration with other agent systems
- **Evaluation suite**: Use ADK's built-in evaluation framework to benchmark agent performance across brand types
