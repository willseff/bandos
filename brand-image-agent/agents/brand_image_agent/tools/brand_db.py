from database.models import Brand, BrandAsset, BrandRule
from database.session import SessionLocal


def load_brand_context(brand_id: str) -> dict:
    """
    Load all brand data needed for agent context: colors, fonts, brand-wide rules,
    and assets with their asset-specific rules.

    Returns a dict matching the shape expected by state["brand_context"].
    """
    session = SessionLocal()
    try:
        brand = session.query(Brand).filter_by(id=brand_id).first()
        if not brand:
            raise ValueError(f"Brand '{brand_id}' not found.")

        # Brand-wide rules (no asset_id)
        brand_rules = (
            session.query(BrandRule)
            .filter_by(brand_id=brand_id, asset_id=None)
            .all()
        )

        # Assets with their specific rules
        assets = session.query(BrandAsset).filter_by(brand_id=brand_id).all()
        asset_dicts = []
        for asset in assets:
            asset_rules = (
                session.query(BrandRule)
                .filter_by(brand_id=brand_id, asset_id=asset.id)
                .all()
            )
            asset_dicts.append({
                "id": asset.id,
                "type": asset.asset_type,
                "name": asset.name,
                "description": asset.description,
                "file_path": asset.file_path,
                "mime_type": asset.mime_type,
                "metadata": asset.meta,
                "rules": [
                    {
                        "id": r.id,
                        "category": r.category,
                        "severity": r.severity,
                        "rule": r.rule_text,
                        "enforcement_prompt": r.enforcement_prompt,
                    }
                    for r in asset_rules
                ],
            })

        return {
            "brand_id": brand.id,
            "brand_name": brand.name,
            "description": brand.description,
            "colors": brand.colors,
            "fonts": brand.fonts,
            "rules": [
                {
                    "id": r.id,
                    "category": r.category,
                    "severity": r.severity,
                    "rule": r.rule_text,
                    "enforcement_prompt": r.enforcement_prompt,
                }
                for r in brand_rules
            ],
            "assets": asset_dicts,
        }
    finally:
        session.close()
