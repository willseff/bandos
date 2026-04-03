import base64
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

GENERATED_DIR = os.getenv("GENERATED_IMAGES_DIR", "./generated")

VALID_ASPECT_RATIOS = {
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3",
    "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
}
VALID_RESOLUTIONS = {"512px", "1K", "2K", "4K"}
VALID_MODES = {"style", "composition", "subject", "brand"}

MODE_PREFIXES = {
    "style": "Match the visual style, color palette, and aesthetic of the reference images. ",
    "composition": "Match the layout, framing, and compositional structure of the reference images. ",
    "subject": "Generate an image featuring the same subject or object shown in the reference images. ",
    "brand": "Match the brand identity shown in the reference images — colors, style, tone, and visual language. ",
}


def generate_with_reference(
    prompt: str,
    reference_images: list[str],
    reference_mode: str = "style",
    aspect_ratio: str = "1:1",
    resolution: str = "1K",
) -> dict:
    """
    Generate an image guided by one or more reference images.

    Args:
        prompt: What to generate.
        reference_images: List of file paths to reference images (max 14).
        reference_mode: How to use the references — style, composition, subject, brand.
        aspect_ratio: One of the supported aspect ratios.
        resolution: One of 512px, 1K, 2K, 4K.

    Returns:
        dict with keys: file_path, generation_time_ms, prompt
    """
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        raise ValueError(f"Invalid aspect_ratio '{aspect_ratio}'. Must be one of {VALID_ASPECT_RATIOS}")
    if resolution not in VALID_RESOLUTIONS:
        raise ValueError(f"Invalid resolution '{resolution}'. Must be one of {VALID_RESOLUTIONS}")
    if reference_mode not in VALID_MODES:
        raise ValueError(f"Invalid reference_mode '{reference_mode}'. Must be one of {VALID_MODES}")
    if not reference_images:
        raise ValueError("At least one reference image is required.")
    if len(reference_images) > 14:
        raise ValueError("Maximum 14 reference images allowed.")

    full_prompt = MODE_PREFIXES[reference_mode] + prompt

    # Build contents: text prompt followed by reference images
    contents = [full_prompt]
    for path in reference_images:
        contents.append(Image.open(path))

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        client = genai.Client(
            vertexai=True,
            project=project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        )
    else:
        client = genai.Client(api_key=os.environ["GOOGLE_GENAI_API_KEY"])

    start = time.time()
    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    elapsed_ms = int((time.time() - start) * 1000)

    # Extract image bytes — skip thought parts
    image_data = None
    for part in response.candidates[0].content.parts:
        if getattr(part, "thought", False):
            continue
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            image_data = part.inline_data.data
            break

    if image_data is None:
        raise RuntimeError("No image returned from Gemini. Full response: " + str(response))

    Path(GENERATED_DIR).mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    file_path = os.path.join(GENERATED_DIR, filename)

    with open(file_path, "wb") as f:
        if isinstance(image_data, str):
            f.write(base64.b64decode(image_data))
        else:
            f.write(image_data)

    return {
        "file_path": file_path,
        "generation_time_ms": elapsed_ms,
        "prompt": full_prompt,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: uv run python -m agents.brand_image_agent.tools.generate_with_reference <ref_image_path>")
        sys.exit(1)
    result = generate_with_reference(
        prompt="A futuristic data center with glowing server racks, dark background, clean minimalist style",
        reference_images=[sys.argv[1]],
        reference_mode="style",
        aspect_ratio="16:9",
        resolution="1K",
    )
    print(f"Generated: {result['file_path']} ({result['generation_time_ms']}ms)")
