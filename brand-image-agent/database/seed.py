"""
Seed a demo brand (Meridian Tech) with colors, fonts, assets, and rules.
Run: uv run python -m database.seed
"""
import json
import os

from database.models import Brand, BrandAsset, BrandRule
from database.session import SessionLocal, init_db


def seed():
    init_db()
    session = SessionLocal()

    # Skip if already seeded
    if session.query(Brand).filter_by(name="Meridian Tech").first():
        print("Already seeded.")
        session.close()
        return

    uploads_dir = os.getenv("UPLOADED_ASSETS_DIR", "./uploads")
    fonts_dir = os.path.join(uploads_dir, "fonts")
    logos_dir = os.path.join(uploads_dir, "logos")
    os.makedirs(fonts_dir, exist_ok=True)
    os.makedirs(logos_dir, exist_ok=True)

    # --- Brand ---
    brand = Brand(
        id="brand_meridian",
        name="Meridian Tech",
        description="Modern SaaS company focused on developer tooling and infrastructure.",
        colors_json=json.dumps({
            "primary": "#0F62FE",
            "secondary": "#6929C4",
            "accent": "#08BDBA",
            "background": "#161616",
            "text_primary": "#F4F4F4",
            "text_secondary": "#C6C6C6",
            "text_on_primary": "#FFFFFF",
            "error": "#DA1E28",
        }),
        fonts_json=json.dumps({
            "heading": "asset_font_heading",
            "body": "asset_font_body",
        }),
    )
    session.add(brand)
    session.flush()

    # --- Font assets (placeholder paths — drop real .ttf files here) ---
    font_heading = BrandAsset(
        id="asset_font_heading",
        brand_id=brand.id,
        asset_type="font",
        name="IBM Plex Sans Bold",
        description="Primary heading font. Use for all headlines and large display text.",
        file_path=os.path.join(fonts_dir, "IBMPlexSans-Bold.ttf"),
        mime_type="font/ttf",
        metadata_json=json.dumps({"weight": "bold", "fallback": "Arial"}),
    )
    font_body = BrandAsset(
        id="asset_font_body",
        brand_id=brand.id,
        asset_type="font",
        name="IBM Plex Sans Regular",
        description="Body font. Use for captions, subtitles, and supporting text.",
        file_path=os.path.join(fonts_dir, "IBMPlexSans-Regular.ttf"),
        mime_type="font/ttf",
        metadata_json=json.dumps({"weight": "regular", "fallback": "Arial"}),
    )

    # --- Logo asset ---
    logo = BrandAsset(
        id="asset_logo_white",
        brand_id=brand.id,
        asset_type="logo",
        name="Primary Logo White",
        description="White variant of the Meridian logo. Use on dark backgrounds only.",
        file_path=os.path.join(logos_dir, "meridian-white.png"),
        mime_type="image/png",
        metadata_json=json.dumps({"variants": ["dark"]}),
    )

    session.add_all([font_heading, font_body, logo])
    session.flush()

    # --- Brand-wide rules ---
    brand_rules = [
        BrandRule(
            brand_id=brand.id,
            category="color",
            severity="critical",
            rule_text="Primary blue (#0F62FE) must be dominant in hero images.",
        ),
        BrandRule(
            brand_id=brand.id,
            category="style",
            severity="warning",
            rule_text="Prefer geometric, clean-line illustrations over photorealistic imagery.",
        ),
        BrandRule(
            brand_id=brand.id,
            category="tone",
            severity="warning",
            rule_text="Imagery should feel technical, precise, and forward-looking.",
        ),
        BrandRule(
            brand_id=brand.id,
            category="color",
            severity="warning",
            rule_text="Dark background (#161616) preferred for hero and banner images.",
        ),
    ]

    # --- Font-specific rules ---
    font_rules = [
        BrandRule(
            brand_id=brand.id,
            asset_id=font_heading.id,
            category="sizing",
            severity="critical",
            rule_text="Minimum font size 24px for headings, never smaller.",
        ),
        BrandRule(
            brand_id=brand.id,
            asset_id=font_heading.id,
            category="pairing",
            severity="warning",
            rule_text="Only pair with text_primary or text_on_primary colors.",
        ),
        BrandRule(
            brand_id=brand.id,
            asset_id=font_heading.id,
            category="typography",
            severity="warning",
            rule_text="Use only for headings and display text, never for body copy.",
        ),
    ]

    # --- Logo-specific rules ---
    logo_rules = [
        BrandRule(
            brand_id=brand.id,
            asset_id=logo.id,
            category="spacing",
            severity="critical",
            rule_text="Minimum 15% clear space around logo on all sides.",
        ),
        BrandRule(
            brand_id=brand.id,
            asset_id=logo.id,
            category="placement",
            severity="critical",
            rule_text="Logo must be in top-left or center, never bottom-right.",
        ),
        BrandRule(
            brand_id=brand.id,
            asset_id=logo.id,
            category="sizing",
            severity="critical",
            rule_text="Logo must be at least 10% of image width, never exceed 25%.",
        ),
        BrandRule(
            brand_id=brand.id,
            asset_id=logo.id,
            category="pairing",
            severity="warning",
            rule_text="Only use white logo variant on dark backgrounds.",
        ),
    ]

    session.add_all(brand_rules + font_rules + logo_rules)
    session.commit()
    session.close()
    print("Seeded Meridian Tech brand.")
    print(f"  Brand ID: {brand.id}")
    print(f"  Font (heading): {font_heading.id} → {font_heading.file_path}")
    print(f"  Font (body):    {font_body.id} → {font_body.file_path}")
    print(f"  Logo:           {logo.id} → {logo.file_path}")
    print("\nDrop real font .ttf files and logo .png into uploads/ to enable render_text and composite tools.")


if __name__ == "__main__":
    seed()
