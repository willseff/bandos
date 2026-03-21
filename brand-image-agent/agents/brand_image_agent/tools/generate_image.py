import base64
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GENERATED_DIR = os.getenv("GENERATED_IMAGES_DIR", "./generated")

VALID_ASPECT_RATIOS = {
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3",
    "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
}
VALID_RESOLUTIONS = {"512px", "1K", "2K", "4K"}


def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    resolution: str = "1K",
    thinking_level: str = "minimal",
) -> dict:
    """
    Generate an image from a text prompt using Gemini image generation.

    Args:
        prompt: Detailed prompt with style, colors, composition.
        aspect_ratio: One of the supported aspect ratios.
        resolution: One of 512px, 1K, 2K, 4K.
        thinking_level: "minimal" or "high".

    Returns:
        dict with keys: file_path, generation_time_ms, prompt
    """
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        raise ValueError(f"Invalid aspect_ratio '{aspect_ratio}'. Must be one of {VALID_ASPECT_RATIOS}")
    if resolution not in VALID_RESOLUTIONS:
        raise ValueError(f"Invalid resolution '{resolution}'. Must be one of {VALID_RESOLUTIONS}")

    client = genai.Client(api_key=os.environ["GOOGLE_GENAI_API_KEY"])

    start = time.time()
    response = client.models.generate_content(
        model="gemini-2.0-flash-preview-image-generation",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_generation_config=types.ImageGenerationConfig(
                image_size=resolution,
            ),
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
        "prompt": prompt,
    }


if __name__ == "__main__":
    # Smoke test
    result = generate_image(
        prompt="A futuristic data center with glowing blue server racks, dark background, geometric shapes, clean minimalist style",
        aspect_ratio="16:9",
        resolution="1K",
    )
    print(f"Generated: {result['file_path']} ({result['generation_time_ms']}ms)")
