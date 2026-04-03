import json
import os
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Float,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _gen_id():
    return os.urandom(8).hex()


class Brand(Base):
    __tablename__ = "brands"

    id = Column(String, primary_key=True, default=_gen_id)
    name = Column(String, nullable=False)
    description = Column(Text)
    colors_json = Column(Text, nullable=False, default="{}")
    fonts_json = Column(Text, nullable=False, default="{}")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assets = relationship("BrandAsset", back_populates="brand", cascade="all, delete-orphan")
    rules = relationship("BrandRule", back_populates="brand", cascade="all, delete-orphan")
    jobs = relationship("GenerationJob", back_populates="brand")

    @property
    def colors(self):
        return json.loads(self.colors_json)

    @property
    def fonts(self):
        return json.loads(self.fonts_json)


class BrandAsset(Base):
    __tablename__ = "brand_assets"

    id = Column(String, primary_key=True, default=_gen_id)
    brand_id = Column(String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    asset_type = Column(String, nullable=False)  # logo | icon | pattern | photo | illustration | font
    name = Column(String, nullable=False)
    description = Column(Text)
    file_path = Column(String, nullable=False)
    mime_type = Column(String)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand", back_populates="assets")
    rules = relationship("BrandRule", back_populates="asset", cascade="all, delete-orphan")

    @property
    def meta(self):
        return json.loads(self.metadata_json)


class BrandRule(Base):
    __tablename__ = "brand_rules"

    id = Column(String, primary_key=True, default=_gen_id)
    brand_id = Column(String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(String, ForeignKey("brand_assets.id", ondelete="CASCADE"), nullable=True)
    category = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="warning")
    rule_text = Column(Text, nullable=False)
    enforcement_prompt = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand", back_populates="rules")
    asset = relationship("BrandAsset", back_populates="rules")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id = Column(String, primary_key=True, default=_gen_id)
    brand_id = Column(String, ForeignKey("brands.id"), nullable=False)
    user_prompt = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending")
    config_json = Column(Text, default="{}")
    selected_image_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    brand = relationship("Brand", back_populates="jobs")
    images = relationship("GeneratedImage", back_populates="job", cascade="all, delete-orphan")

    @property
    def config(self):
        return json.loads(self.config_json)


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id = Column(String, primary_key=True, default=_gen_id)
    job_id = Column(String, ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False)
    iteration = Column(Integer, nullable=False, default=1)
    variation = Column(Integer, nullable=False)
    engineered_prompt = Column(Text, nullable=False)
    file_path = Column(String, nullable=True)
    score = Column(Float, nullable=True)
    rule_violations_json = Column(Text, nullable=True)
    judge_feedback = Column(Text, nullable=True)
    generation_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("GenerationJob", back_populates="images")

    @property
    def rule_violations(self):
        return json.loads(self.rule_violations_json) if self.rule_violations_json else []


# Indexes
Index("idx_rules_brand", BrandRule.brand_id)
Index("idx_rules_asset", BrandRule.asset_id)
Index("idx_assets_brand", BrandAsset.brand_id)
Index("idx_jobs_brand", GenerationJob.brand_id)
Index("idx_images_job", GeneratedImage.job_id)
