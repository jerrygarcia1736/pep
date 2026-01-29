from __future__ import annotations

import os
import json
import requests
import secrets
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Tuple

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound

# ✅ FIX IS HERE — Text added
from sqlalchemy import Column, Integer, String, DateTime, Float, Text, text

from config import Config
from models import get_session, create_engine, Base as ModelBase

# Import nutrition API
from nutrition_api import register_nutrition_routes

# -----------------------------------------------------------------------------
# Goal -> peptide association (educational tags, NOT medical advice)
# -----------------------------------------------------------------------------
GOAL_TO_PEPTIDES: dict[str, list[str]] = {
    "fat_loss": ["Semaglutide", "Tirzepatide", "Tesamorelin", "AOD 9604", "CJC-1295", "Ipamorelin"],
    "muscle_gain": ["CJC-1295", "Ipamorelin", "GHRP-2", "GHRP-6", "IGF-1 LR3"],
    "injury_recovery": ["BPC-157", "TB-500", "GHK-Cu"],
    "longevity": ["Epithalon", "MOTS-c", "Thymosin Alpha-1", "NAD+", "CJC-1295"],
    "skin_health": ["GHK-Cu", "Melanotan II"],
    "cognitive_enhancement": ["Semax", "Selank", "Noopept", "DSIP"],
}

GOAL_LABELS: dict[str, str] = {
    "fat_loss": "Fat Loss",
    "muscle_gain": "Muscle Gain",
    "injury_recovery": "Injury Recovery",
    "longevity": "Longevity",
    "skin_health": "Skin Health",
    "cognitive_enhancement": "Cognitive Enhancement",
}

# -----------------------------------------------------------------------------
# Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class User(ModelBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    tier = Column(String(20), nullable=False, default="free")
    created_at = Column(DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class PepAIUsage(ModelBase):
    __tablename__ = "pep_ai_usage"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True)
    used = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FoodLog(ModelBase):
    __tablename__ = "food_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    description = Column(String(500), nullable=False)

    total_calories = Column(Float, default=0)
    total_protein_g = Column(Float, default=0)
    total_fat_g = Column(Float, default=0)
    total_carbs_g = Column(Float, default=0)

    raw_data = Column(String(5000))


class PasswordResetToken(ModelBase):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    token = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Integer, default=0)


class UserProfile(ModelBase):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)
    age = Column(Integer)
    weight_lbs = Column(Float)
    height_inches = Column(Float)
    gender = Column(String(20))
    goals = Column(String(500))
    experience_level = Column(String(20))
    medical_notes = Column(String(1000))
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# -----------------------------------------------------------------------------
# DB init
# -----------------------------------------------------------------------------
db_url = Config.DATABASE_URL
engine = create_engine(db_url)

ModelBase.metadata.create_all(engine)

# -----------------------------------------------------------------------------
# Register USDA Nutrition API Routes
# -----------------------------------------------------------------------------
register_nutrition_routes(app)

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
