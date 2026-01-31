"""
Peptide Tracker Web Application (Template-contract safe)

UPDATED: 
- Added USDA Nutrition API integration
- Added password reset functionality
- Fixed calculator route (now peptide-calculator)
"""

from __future__ import annotations

import os
import io
import json
import re
import hashlib
import requests
import secrets
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Tuple

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, render_template_string
import base64
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound

from sqlalchemy import Column, Integer, String, DateTime, Float, text, func
from config import Config
from models import get_session, create_engine, Base as ModelBase

# Import nutrition API
from nutrition_api import register_nutrition_routes
from confidence import compute_injection_confidence



# -----------------------------------------------------------------------------
# Lightweight image preprocessing (optional)
# - Improves OCR/handwriting results from phone photos
# - Uses Pillow if installed; otherwise no-op
# -----------------------------------------------------------------------------
try:
    from PIL import Image, ImageOps, ImageEnhance, ImageFilter  # type: ignore
except Exception:  # Pillow not installed
    Image = None  # type: ignore

def _preprocess_for_vision(image_bytes: bytes) -> bytes:
    """Best-effort preprocessing to improve vision/OCR accuracy.

    - Fix iPhone EXIF rotation
    - Autocontrast + sharpen
    - Resize down to a sane max dimension for speed
    """
    if Image is None:
        return image_bytes
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")

        max_side = 1600
        w, h = img.size
        scale = max(w, h) / max_side
        if scale > 1:
            img = img.resize((int(w / scale), int(h / scale)))

        img = ImageOps.autocontrast(img)
        img = ImageEnhance.Sharpness(img).enhance(1.7)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90, optimize=True)
        return out.getvalue()
    except Exception:
        return image_bytes

def _fingerprint_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _openai_identify_food_from_image(image_b64: str, mime_type: str = "image/jpeg") -> dict:
    """Identify a food item from an image using the OpenAI Responses API.

    Returns dict: {name, confidence, alternatives, notes}
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}

    # Use a vision-capable model available on the Responses API.
    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini")

    data_url = f"data:{mime_type};base64,{image_b64}"

    prompt = """
You are a nutrition assistant. Analyze the photo and return ONLY strict JSON.
Goal: identify the food item as accurately as possible. If the item is packaged and a label is visible, use the visible text to determine the exact variant (e.g., diet/zero sugar/mini/caffeine-free).

Return JSON with this exact schema:
{
  "name": string,                 # canonical food name with key modifiers (e.g., "Diet Canada Dry Ginger Ale")
  "confidence": number,           # 0-1
  "alternatives": [string],       # up to 3 plausible alternatives
  "notes": string,                # short notes about what you saw / assumptions
  "nutrition": {                  # ONLY if you can read a nutrition label clearly
     "serving_desc": string,
     "calories": number,
     "protein_g": number,
     "carbs_g": number,
     "fat_g": number
  } | null
}

Rules:
- If you cannot read the nutrition label clearly, set nutrition to null (do NOT guess).
- Prefer accuracy over verbosity. No markdown, no extra text.
""".strip()

    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url}
                ],
            }
        ],
    }

    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=45,
    )
    if r.status_code >= 400:
        return {"error": f"OpenAI API error {r.status_code}", "details": r.text[:2000]}

    resp = r.json()
    # Responses API commonly provides output_text convenience in some SDKs; raw JSON has output items.
    # We'll extract text from output content parts.
    text_parts = []
    for item in resp.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text"):
                text_parts.append(c.get("text", ""))
    out_text = "\n".join([t for t in text_parts if t]).strip()

    if not out_text:
        # fallback: some responses may include 'output_text' at top-level in docs examples
        out_text = (resp.get("output_text") or "").strip()

    if not out_text:
        return {"error": "No text returned from model"}

    # Parse JSON safely
    try:
        return json.loads(out_text)
    except Exception:
        # try to locate a JSON object in the text
        m = re.search(r"\{.*\}", out_text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"error": "Model returned non-JSON", "raw": out_text[:2000]}


# -----------------------------------------------------------------------------
# Equipment / gym scan helper (category-level MVP)
# -----------------------------------------------------------------------------
_EQUIPMENT_CATEGORIES = [
    {"key": "machine_strength", "label": "Strength Machine"},
    {"key": "cables", "label": "Cable Machine"},
    {"key": "free_weights", "label": "Free Weights"},
    {"key": "cardio", "label": "Cardio"},
    {"key": "other", "label": "Other / Unknown"},
]

def _coerce_equipment_category(cat: str | None) -> str:
    if not cat:
        return "other"
    cat = str(cat).strip().lower()
    allowed = {c["key"] for c in _EQUIPMENT_CATEGORIES}
    # common aliases
    aliases = {
        "machine": "machine_strength",
        "strength_machine": "machine_strength",
        "strength": "machine_strength",
        "cable": "cables",
        "cable_machine": "cables",
        "freeweight": "free_weights",
        "free weight": "free_weights",
        "weights": "free_weights",
        "dumbbells": "free_weights",
        "barbell": "free_weights",
        "treadmill": "cardio",
        "bike": "cardio",
        "elliptical": "cardio",
    }
    cat = aliases.get(cat, cat)
    return cat if cat in allowed else "other"

def _openai_identify_equipment_from_image(image_b64: str, mime_type: str = "image/jpeg") -> dict:
    """Identify gym equipment category from an image using OpenAI Responses API.

    Returns dict: {category, confidence, alternatives, notes}
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}

    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    data_url = f"data:{mime_type};base64,{image_b64}"

    allowed = [c["key"] for c in _EQUIPMENT_CATEGORIES]
    prompt = f"""
You are a gym equipment classifier. Analyze the photo and return ONLY strict JSON.

Goal: classify the equipment into ONE category from this allowed list:
{allowed}

Return JSON with this exact schema:
{{
  "category": string,        # one of the allowed list
  "confidence": number,      # 0-1
  "alternatives": [string],  # up to 3 from the allowed list (excluding category)
  "notes": string            # short notes about what you saw
}}

Rules:
- If uncertain, choose "other" with low confidence.
- Do not guess specific exercise names.
- No markdown, no extra text.
""".strip()

    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
    }

    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=45,
    )
    if r.status_code >= 400:
        return {"error": f"OpenAI API error {r.status_code}", "details": r.text[:2000]}

    try:
        data = r.json()
        out = data.get("output", [])
        txt = ""
        for item in out:
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text":
                    txt += c.get("text", "")
        txt = (txt or "").strip()
        j = json.loads(txt)
        cat = _coerce_equipment_category(j.get("category"))
        conf = float(j.get("confidence") or 0)
        alts_raw = j.get("alternatives") or []
        alts = []
        for a in alts_raw[:3]:
            a2 = _coerce_equipment_category(a)
            if a2 != cat and a2 not in alts:
                alts.append(a2)
        return {
            "category": cat,
            "confidence": max(0.0, min(1.0, conf)),
            "alternatives": alts,
            "notes": (j.get("notes") or "")[:300],
        }
    except Exception:
        return {"error": "Failed to parse OpenAI response", "details": r.text[:2000]}


# -----------------------------------------------------------------------------
# USDA macro lookup helper (FoodData Central)
# -----------------------------------------------------------------------------
def _usda_lookup_macros(food_query: str) -> dict:
    """Lookup calories + macros for a food using USDA FoodData Central search.

    Returns dict with keys: calories, protein, carbs, fat, serving_size_g, source.
    Best-effort; returns {"error": "..."} on failure.
    """
    api_key = os.environ.get("USDA_API_KEY") or os.environ.get("USDA_FOOD_API_KEY")
    if not api_key:
        return {"error": "USDA_API_KEY not set"}

    try:
        r = requests.get(
            "https://api.nal.usda.gov/fdc/v1/foods/search",
            params={"api_key": api_key, "query": food_query, "pageSize": 5},
            timeout=20,
        )
        if r.status_code >= 400:
            return {"error": f"USDA API error {r.status_code}", "details": r.text[:500]}

        j = r.json() or {}
        foods = j.get("foods") or []
        if not foods:
            return {"error": "No USDA matches"}

        best = foods[0]
        nutrients = best.get("foodNutrients") or []

        def _pick(*names_or_ids):
            for n in nutrients:
                nid = n.get("nutrientId")
                nm = (n.get("nutrientName") or "").lower()
                unit = (n.get("unitName") or "").lower()
                val = n.get("value")
                for x in names_or_ids:
                    if isinstance(x, int) and nid == x and val is not None:
                        return float(val)
                    if isinstance(x, str) and x.lower() in nm and val is not None:
                        return float(val)
            return None

        # Common nutrient IDs:
        # 1008 Energy (kcal), 1003 Protein, 1005 Carbohydrate, 1004 Total lipid (fat)
        kcal_100g = _pick(1008, "energy")
        protein_100g = _pick(1003, "protein")
        carbs_100g = _pick(1005, "carbohydrate")
        fat_100g = _pick(1004, "total lipid", "fat")

        # Determine serving size (best-effort). Many foods have servingSize in grams.
        serving_size = best.get("servingSize")
        serving_unit = (best.get("servingSizeUnit") or "").lower()

        serving_g = None
        if serving_size and isinstance(serving_size, (int, float)) and serving_unit in ("g", "gram", "grams"):
            serving_g = float(serving_size)

        # Convert per-100g to per-serving if we have grams; else keep per-100g.
        factor = (serving_g / 100.0) if serving_g else 1.0

        out = {
            "calories": round((kcal_100g or 0) * factor, 1) if kcal_100g is not None else None,
            "protein": round((protein_100g or 0) * factor, 1) if protein_100g is not None else None,
            "carbs": round((carbs_100g or 0) * factor, 1) if carbs_100g is not None else None,
            "fat": round((fat_100g or 0) * factor, 1) if fat_100g is not None else None,
            "serving_size_g": serving_g,  # None means "per 100g"
            "source": "usda_fdc_search",
            "fdc_id": best.get("fdcId"),
            "matched_description": best.get("description") or best.get("lowercaseDescription"),
        }
        return out
    except Exception as e:
        return {"error": f"USDA lookup failed: {e}"}


# -----------------------------------------------------------------------------
# Peptide label scan helper (OpenAI vision)
# -----------------------------------------------------------------------------
def _openai_scan_peptide_label(image_b64: str, peptide_names: list[str], mime_type: str = "image/jpeg") -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}

    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    data_url = f"data:{mime_type};base64,{image_b64}"

    # Provide the model a constrained list to reduce hallucinations and improve handwriting guesses
    known_list = ", ".join([p for p in (peptide_names or []) if p])[:6000]

    prompt = f"""
You are an OCR + parsing assistant for peptide vial/box labels (printed OR handwritten).
Extract the most likely peptide name(s) and any quantity information from the label.

Strong preference:
- Choose peptide names from this known list when possible:
{known_list}

User's most common peptides (extra bias):
{", ".join(TOP_PEPTIDES)}

Return ONLY strict JSON with this schema:
{{
  "text": string,                  # best-effort transcription of visible label text
  "peptides": [string],            # peptide names found (best guess)
  "quantities": [
    {{"amount": number, "unit": "mg"|"mcg"|"iu"|null}}
  ],
  "confidence": number,            # 0-1 overall confidence
  "candidates": [string]           # up to 8 likely peptide name guesses if uncertain
}}

Rules:
- If handwritten is unclear, still provide candidates (best guesses).
- Normalize common forms: TB500→TB-500, BPC 157→BPC-157, PT141→PT-141, MT2→MT-2, semiglutide→semaglutide.
- Keep output as JSON only. No markdown, no extra text.
""".strip()

    payload = {
        "model": model,
        "input": [
            {"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url},
            ]}
        ],
    }

    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=45,
    )
    if r.status_code >= 400:
        return {"error": f"OpenAI API error {r.status_code}", "details": r.text[:2000]}

    resp = r.json()
    text_parts = []
    for item in resp.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text"):
                text_parts.append(c.get("text", ""))
    out_text = "\n".join([t for t in text_parts if t]).stclass EquipmentScan(ModelBase):
    __tablename__ = "equipment_scans"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    image_sha = Column(String(64), nullable=True, index=True)
    predicted_category = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    alternatives_json = Column(String(500), nullable=True)
    notes = Column(String(300), nullable=True)
    corrected_category = Column(String(50), nullable=True)

class WorkoutLog(ModelBase):
    __tablename__ = "workout_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    performed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    equipment_category = Column(String(50), nullable=False, index=True)
    exercise_name = Column(String(120), nullable=True)
    sets = Column(Integer, nullable=True)
    reps = Column(Integer, nullable=True)
    weight = Column(Float, nullable=True)
    notes = Column(String(300), nullable=True)

rip() or (resp.get("output_text") or "").strip()
    if not out_text:
        return {"error": "No text returned from model"}

    try:
        return json.loads(out_text)
    except Exception:
        m = re.search(r"\{.*\}", out_text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"error": "Model returned non-JSON", "raw": out_text[:2000]}


# -----------------------------------------------------------------------------
# Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# ----------------------------
# Helpers
# ----------------------------
def has_endpoint(name: str) -> bool:
    """Return True if a Flask endpoint exists.

    NOTE: This must be module-level so it can be used both in templates (via context processor)
    and inside route functions (e.g., scan_nutrition)."""
    try:
        return name in app.view_functions
    except Exception:
        return False


def register_route(rule: str, endpoint: str, view_func, **options):
    """Idempotent route registration to prevent duplicate endpoint crashes."""
    if endpoint in app.view_functions:
        return
    app.add_url_rule(rule, endpoint=endpoint, view_func=view_func, **options)



# Jinja filter for parsing JSON in templates
@app.template_filter('from_json')
def from_json_filter(value):
    """Parse JSON string in templates"""
    if not value:
        return []
    try:
        return json.loads(value)
    except:
        return []

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class User(ModelBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    tier = Column(String(20), nullable=False, default="free")  # free | tier1 | tier2 | admin
    created_at = Column(DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

# Food log model for nutrition tracking

class PepAIUsage(ModelBase):
    """Tracks Pep AI usage for free-tier limits (one row per user)."""
    __tablename__ = "pep_ai_usage"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True)
    used = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FoodLog(ModelBase):
    __tablename__ = "food_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    description = Column(String(500), nullable=False)

    # Legacy totals (kept for dashboard summaries)
    total_calories = Column(Float, default=0)
    total_protein_g = Column(Float, default=0)
    total_fat_g = Column(Float, default=0)
    total_carbs_g = Column(Float, default=0)

    # Normalized fields (used by Scan Food edit UI)
    food_name = Column(String(200))
    calories = Column(Float)
    protein_g = Column(Float)
    carbs_g = Column(Float)
    fat_g = Column(Float)
    serving_size_g = Column(Float)

    source = Column(String(50))
    confidence = Column(Float)  # 0-1
    fingerprint = Column(String(64), index=True)
    raw_text = Column(String(2000))
    alternatives_json = Column(String(2000))
    notes = Column(String(500))

    raw_data = Column(String(5000))

class ScanCorrection(ModelBase):
    __tablename__ = "scan_corrections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    scan_type = Column(String(20), nullable=False, index=True)  # "peptide" | "food"
    fingerprint = Column(String(64), nullable=False, index=True)
    original = Column(String(400))
    corrected = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Password reset token model
class PasswordResetToken(ModelBase):
    __tablename__ = "password_reset_tokens"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    token = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Integer, default=0)  # 0 = not used, 1 = used

# User Profile model for personalized AI
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


class DisclaimerAcceptance(ModelBase):
    __tablename__ = "disclaimer_acceptance"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True)
    accepted_at = Column(DateTime, default=datetime.utcnow)


# -----------------------------------------------------------------------------
# DB init + migration
# -----------------------------------------------------------------------------
FREE_PEP_AI_LIMIT = int(os.environ.get("FREE_PEP_AI_LIMIT", 10))

db_url = Config.DATABASE_URL
engine = create_engine(db_url)

def ensure_users_tier_column(engine) -> None:
    """Add users.tier on legacy DBs (safe no-op if already present)."""
    try:
        dialect = (engine.dialect.name or "").lower()
        if dialect.startswith("postgres"):
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS tier VARCHAR(20) DEFAULT 'free';")
                )
        elif dialect.startswith("sqlite"):
            with engine.begin() as conn:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users);")).fetchall()]
                if "tier" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN tier VARCHAR(20) DEFAULT 'free';"))
    except Exception as e:
        print(f"Warning: could not ensure users.tier column: {e}")


def ensure_food_logs_columns(engine) -> None:
    """Add new columns used by Scan Food edit UI (safe no-op if present)."""
    try:
        dialect = (engine.dialect.name or "").lower()
        if dialect.startswith("postgres"):
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS food_name VARCHAR(200);"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS calories DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS protein_g DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS carbs_g DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS fat_g DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS serving_size_g DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS source VARCHAR(50);"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64);"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS raw_text VARCHAR(2000);"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS alternatives_json VARCHAR(2000);"))
                conn.execute(text("ALTER TABLE IF EXISTS food_logs ADD COLUMN IF NOT EXISTS notes VARCHAR(500);"))
        elif dialect.startswith("sqlite"):
            with engine.begin() as conn:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(food_logs);")).fetchall()]
                def add(col_sql: str, col_name: str):
                    if col_name not in cols:
                        conn.execute(text(f"ALTER TABLE food_logs ADD COLUMN {col_sql};"))
                add("food_name VARCHAR(200)", "food_name")
                add("calories REAL", "calories")
                add("protein_g REAL", "protein_g")
                add("carbs_g REAL", "carbs_g")
                add("fat_g REAL", "fat_g")
                add("serving_size_g REAL", "serving_size_g")
                add("source VARCHAR(50)", "source")
                add("confidence REAL", "confidence")
                add("fingerprint VARCHAR(64)", "fingerprint")
                add("raw_text VARCHAR(2000)", "raw_text")
                add("alternatives_json VARCHAR(2000)", "alternatives_json")
                add("notes VARCHAR(500)", "notes")
    except Exception as e:
        print(f"Warning: could not ensure food_logs columns: {e}")

ModelBase.metadata.create_all(engine)
ensure_users_tier_column(engine)
ensure_food_logs_columns(engine)

# -----------------------------------------------------------------------------
# Register USDA Nutrition API Routes
# -----------------------------------------------------------------------------
register_nutrition_routes(app)

# -----------------------------------------------------------------------------
# Tier helpers
# -----------------------------------------------------------------------------
TIER_ORDER = {"free": 0, "tier1": 1, "tier2": 2, "admin": 3}

def tier_at_least(tier: str, minimum: str) -> bool:
    return TIER_ORDER.get(tier or "free", 0) >= TIER_ORDER.get(minimum, 0)

# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in.", "warning")
            return redirect(url_for("login"))

        # ---------------------------------------------------------------------
        # Profile is OPTIONAL.
        # We only gate a small set of "personalized / higher-risk" features (Pep AI),
        # while allowing the rest of the app (including scanners) to work normally.
        #
        # If the user clicks "Skip for now", we set session["profile_skipped"]=True
        # and we should respect that for the rest of the session.
        # ---------------------------------------------------------------------
        restricted_until_profile_complete = {"chat", "api_chat", "pep_ai"}

        if (f.__name__ in restricted_until_profile_complete) and (not session.get("profile_skipped")):
            db = get_session(db_url)
            try:
                profile = db.query(UserProfile).filter_by(user_id=session["user_id"]).first()
                if not profile or not profile.completed_at:
                    flash("Complete your (optional) profile to unlock Pep AI.", "info")
                    return redirect(url_for("dashboard"))
            finally:
                db.close()

        return f(*args, **kwargs)
    return wrapper

def get_current_user():
    if "user_id" not in session:
        return None
    db = get_session(db_url)
    try:
        return db.query(User).filter_by(id=session["user_id"]).first()
    finally:
        db.close()


# -----------------------------------------------------------------------------
# Onboarding helpers (2 steps)
# Step 1: Profile setup
# Step 2: Disclaimer acknowledgement
# -----------------------------------------------------------------------------
def get_user_profile(user_id: int):
    db = get_session(db_url)
    try:
        return db.query(UserProfile).filter_by(user_id=user_id).first()
    finally:
        db.close()

def is_profile_complete(user_id: int) -> bool:
    p = get_user_profile(user_id)
    return bool(p and p.completed_at)

def has_accepted_disclaimer(user_id: int) -> bool:
    db = get_session(db_url)
    try:
        return db.query(DisclaimerAcceptance).filter_by(user_id=user_id).first() is not None
    finally:
        db.close()

def require_onboarding(view_func):
    """Lightweight gate: requires login, but does NOT force onboarding redirects.

    Profile + disclaimer are optional and can be completed later.
    Individual features can check profile/disclaimer as needed.
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        u = get_current_user()
        if not u:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapper


# -----------------------------------------------------------------------------
# Jinja helpers
# -----------------------------------------------------------------------------
class AnonymousUser:
    is_authenticated = False
    tier = "free"
    email = None

@app.context_processor
def inject_template_helpers():
    user = get_current_user()

    def has_endpoint(name: str) -> bool:
        return name in app.view_functions

    if not user:
        # Not logged in
        return {
            "current_user": AnonymousUser(),
            "has_endpoint": has_endpoint,
            "tier_at_least": tier_at_least,
            "pep_ai_remaining": (lambda: None),
        }

    # Logged in
    user.is_authenticated = True
    if not getattr(user, "tier", None):
        user.tier = "free"

    def pep_ai_remaining() -> int | None:
        """Remaining free Pep AI uses for current user.
        - None means unlimited (tier1+)
        - 0+ means remaining free uses for free tier
        """
        try:
            if tier_at_least(user.tier, "tier1"):
                return None
            db = get_session(db_url)
            try:
                usage = db.query(PepAIUsage).filter_by(user_id=user.id).first()
                used = usage.used if usage else 0
                return max(FREE_PEP_AI_LIMIT - used, 0)
            finally:
                db.close()
        except Exception:
            return None

    return {
        "current_user": user,
        "has_endpoint": has_endpoint,
        "tier_at_least": tier_at_least,
        "pep_ai_remaining": pep_ai_remaining,
    }

# -----------------------------------------------------------------------------
# Utility: render template if it exists
# -----------------------------------------------------------------------------
def render_if_exists(template_name: str, fallback_endpoint: str = "dashboard", **ctx):
    try:
        return render_template(template_name, **ctx)
    except TemplateNotFound:
        return redirect(url_for(fallback_endpoint))

# -----------------------------------------------------------------------------
# Dashboard context (safe defaults)
# -----------------------------------------------------------------------------
def _compute_dashboard_context() -> Tuple[Dict[str, Any], List[Any], List[Any]]:
    stats = {"active_protocols": 0, "active_vials": 0, "injections_this_week": 0, "total_peptides": 0}
    protocols: List[Any] = []
    recent_injections: List[Any] = []

    # Best-effort: use your project's DB helper if present; otherwise defaults
    try:
        from database import PeptideDB  # type: ignore

        db = get_session(db_url)
        try:
            pdb = PeptideDB(db)
            protocols = getattr(pdb, "list_active_protocols", lambda: [])()
            recent_injections = getattr(pdb, "get_recent_injections", lambda days=7: [])(days=7)
            active_vials = getattr(pdb, "list_active_vials", lambda: [])()
            all_peptides = getattr(pdb, "list_peptides", lambda: [])()
            stats = {
                "active_protocols": len(protocols),
                "active_vials": len(active_vials),
                "injections_this_week": len(recent_injections),
                "total_peptides": len(all_peptides),
            }
        finally:
            db.close()
    except Exception as e:
        print(f"Dashboard context fallback (non-fatal): {e}")

    return stats, protocols, recent_injections


# -----------------------------------------------------------------------------
# Shared loader: peptides list for forms (best-effort)
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Peptide seeding (ensures dropdowns have options on fresh DBs)
# -----------------------------------------------------------------------------
DEFAULT_PEPTIDES: list[tuple[str, str]] = [
    ("BPC-157", "Body Protection Compound-157"),
    ("TB-500", "Thymosin Beta-4"),
    ("Epitalon", "Epithalon"),
    ("GHK-Cu", "Copper Peptide (GHK-Cu)"),
    ("KPV", "KPV"),
    ("DSIP", "Delta Sleep-Inducing Peptide"),
    ("CJC-1295", "CJC-1295"),
    ("Ipamorelin", "Ipamorelin"),
    ("Selank", "Selank"),
    ("Semax", "Semax"),
    ("MT2", "Melanotan II (MT2)"),
    ("PT-141", "Bremelanotide (PT-141)"),
    ("Thymosin Alpha-1", "Thymosin Alpha-1 (TA-1)"),
    ("MOTS-c", "MOTS-c"),
    ("SS-31", "Elamipretide (SS-31)"),
    ("AOD-9604", "AOD-9604"),
    ("Tesamorelin", "Tesamorelin"),
    ("Sermorelin", "Sermorelin"),
    ("GHRP-2", "GHRP-2"),
    ("GHRP-6", "GHRP-6"),
    ("Hexarelin", "Hexarelin"),
    ("BPC-157 (Oral)", "BPC-157 (Oral)"),
    ("NAD+", "NAD+"),
    ("Glutathione", "Glutathione"),
    ("Melatonin", "Melatonin"),
    ("IGF-1 LR3", "IGF-1 LR3"),
    ("PEG-MGF", "PEG-MGF"),
    ("Follistatin-344", "Follistatin-344"),
    ("Kisspeptin-10", "Kisspeptin-10"),
    ("TB-4 Frag", "Thymosin Beta-4 Fragment"),
    ("B7-33", "Relaxin-2 analog (B7-33)"),
    ("ARA-290", "ARA-290"),
    ("LL-37", "LL-37"),
    ("Bremelanotide", "Bremelanotide"),
    ("Oxytocin", "Oxytocin"),
    ("DSIP (Alt)", "DSIP"),
    ("KPV (Alt)", "KPV"),
    ("Epithalon", "Epitalon / Epithalon"),
    ("Thymalin", "Thymalin"),
]

# -----------------------------------------------------------------------------
# Scan Peptides: normalization + ranking helpers (handwriting-friendly)
# -----------------------------------------------------------------------------
TOP_PEPTIDES: list[str] = [
    "BPC-157",
    "TB-500",
    "GHK-Cu",
    "DSIP",
    "MT-2",
    "PT-141",
    "Retatrutide",
    "Tirzepatide",
    "Semaglutide",
    "Semax",
    "Selank",
]

def _norm_pep(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("_", "-").replace("—", "-").replace("–", "-")
    s = re.sub(r"\s+", " ", s)

    # common alias fixes
    s = s.replace("bpc 157", "bpc-157").replace("bpc157", "bpc-157")
    s = s.replace("tb500", "tb-500").replace("tb 500", "tb-500").replace("tb-500", "tb-500")
    s = s.replace("pt141", "pt-141").replace("pt 141", "pt-141")
    s = s.replace("mt2", "mt-2").replace("mt 2", "mt-2")
    s = s.replace("ghk cu", "ghk-cu").replace("ghk-cu", "ghk-cu")
    s = s.replace("semiglutide", "semaglutide")  # common misspelling
    return s

def _fuzzy_ratio(a: str, b: str) -> float:
    # fast and dependency-free
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()

def _best_peptide_matches(raw_candidates: list[str], peptide_names: list[str], limit: int = 5) -> list[dict]:
    """Rank peptide matches from model output against known peptide names."""
    # library = DB peptides + user's top peptides (dedup, preserve order)
    lib = []
    seen = set()
    for p in (peptide_names or []) + TOP_PEPTIDES:
        if not p:
            continue
        key = p.strip()
        if key and key not in seen:
            seen.add(key)
            lib.append(key)

    lib_norm = [(p, _norm_pep(p)) for p in lib]
    scored: dict[str, float] = {}

    for cand in raw_candidates or []:
        cn = _norm_pep(cand)
        if not cn:
            continue
        for p, pn in lib_norm:
            r = _fuzzy_ratio(cn, pn)
            if r >= 0.55:
                scored[p] = max(scored.get(p, 0.0), r)

    # boost top peptides slightly
    for p in TOP_PEPTIDES:
        if p in scored:
            scored[p] = min(1.0, scored[p] + 0.08)

    out = [{"name": k, "confidence": float(v)} for k, v in sorted(scored.items(), key=lambda x: x[1], reverse=True)]
    return out[:limit]

def _seed_peptides_if_empty(pdb) -> None:
    """Seed a baseline peptide list on fresh databases.

    Safe to call repeatedly; does nothing if peptides already exist.
    """
    try:
        existing = getattr(pdb, "list_peptides", lambda: [])()
        if existing:
            return
        add_fn = getattr(pdb, "add_peptide", None)
        if not callable(add_fn):
            return
        for name, common_name in DEFAULT_PEPTIDES:
            try:
                add_fn(name=name, common_name=common_name)
            except Exception:
                # Ignore duplicates / constraint errors
                continue
    except Exception:
        # Never block the app for seeding issues
        app.logger.exception("Peptide seeding failed (non-fatal).")

def _load_peptides_list() -> list[Any]:
    """Return peptides from DB (and seed defaults on a fresh DB).

    This powers dropdowns like Add Vial / Add Protocol.
    """
    try:
        from database import PeptideDB  # type: ignore
        db = get_session(db_url)
        try:
            pdb = PeptideDB(db)
            _seed_peptides_if_empty(pdb)
            return getattr(pdb, "list_peptides", lambda: [])()
        finally:
            db.close()
    except Exception as e:
        app.logger.info("Could not load peptides list (non-fatal): %s", e)
        return []

# -----------------------------------------------------------------------------
# Protocol templates (names + metadata only; user sets dosing)
# -----------------------------------------------------------------------------
PROTOCOL_TEMPLATES: dict[str, dict[str, str]] = {
    "bpc157": {"name": "BPC-157", "protocol_name": "BPC-157 Healing Protocol"},
    "tb500": {"name": "TB-500", "protocol_name": "TB-500 Recovery Protocol"},
    "epitalon": {"name": "Epitalon", "protocol_name": "Epitalon Sleep & Longevity Protocol"},
    "ghkcu": {"name": "GHK-Cu", "protocol_name": "GHK-Cu Skin & Repair Protocol"},
    "mt2": {"name": "MT2", "protocol_name": "MT2 Tanning Protocol"},
    "kpv": {"name": "KPV", "protocol_name": "KPV Protocol"},
    "dsip": {"name": "DSIP", "protocol_name": "DSIP Protocol"},
    "cjc1295": {"name": "CJC-1295", "protocol_name": "CJC-1295 Protocol"},
    "ipamorelin": {"name": "Ipamorelin", "protocol_name": "Ipamorelin Protocol"},
    "selank": {"name": "Selank", "protocol_name": "Selank Protocol"},
}


# -----------------------------------------------------------------------------
# Core routes
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Scan Food + Scan Peptides (NO templates, NO docker)
# - Scan Food: photo -> AI guess (MobileNet) OR OCR text (Tesseract.js)
# - Scan Peptides: OCR text -> match to known peptides
# -----------------------------------------------------------------------------

@app.route("/scan-food-photo", methods=["GET"])
@login_required
def scan_food_photo():
    # Photo-of-food recognition (no label). Uses OpenAI vision + quick portion prompt.
    html = """<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Photo of Food</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; margin:16px; background:#f7f7fb;}
    .card{background:#fff;border:1px solid #e6e6ef;border-radius:14px;padding:14px;box-shadow:0 1px 8px rgba(0,0,0,.04); max-width:720px; margin:0 auto;}
    h1{font-size:20px;margin:0 0 6px;}
    .muted{color:#666;font-size:13px;line-height:1.4}
    .btn{display:inline-flex;align-items:center;justify-content:center; gap:8px; padding:10px 12px; border-radius:12px; border:1px solid #d9d9e6; background:#111827; color:#fff; font-weight:800; cursor:pointer;}
    .btn.secondary{background:#fff;color:#111827;}
    .btn:disabled{opacity:.5;cursor:not-allowed;}
    input[type=file]{width:100%;}
    .row{display:flex; gap:10px; flex-wrap:wrap; margin-top:10px;}
    .box{border:1px dashed #d9d9e6; border-radius:12px; padding:10px; background:#fafafe; margin-top:10px;}
    img{max-width:100%; border-radius:12px; border:1px solid #e6e6ef; margin-top:10px;}
    select,input{width:100%; padding:10px; border-radius:12px; border:1px solid #e6e6ef;}
    .pill{display:inline-block; padding:6px 10px; border-radius:999px; border:1px solid #e6e6ef; background:#fff; font-size:12px; color:#111827;}
  </style>
</head>
<body>
  <div class="card">
    <h1>📸 Photo of Food</h1>
    <div class="muted">Snap a photo (e.g., an apple). We’ll identify it, then you pick a portion size.</div>

    <div class="box">
      <div class="muted"><b>Accuracy tips:</b> good light, food centered, avoid motion blur, fill the frame.</div>
    </div>

    <div style="margin-top:10px;">
      <input id="foodPhoto" type="file" accept="image/*" capture="environment" style="display:none" />
      <input id="foodUpload" type="file" accept="image/*" style="display:none" />
      <div class="d-flex gap-2 mt-2">
        <button id="btnStartCam" type="button" class="btn btn-success flex-fill">
          <i class="bi bi-camera"></i> Start Camera
        </button>
        <button id="btnUpload" type="button" class="btn btn-outline-primary flex-fill">
          <i class="bi bi-upload"></i> Upload Photo
        </button>
      </div>
      <img id="preview" style="display:none;" alt="preview"/>
    </div>

    <div class="row">
      <button class="btn" id="btnIdentify" type="button" disabled>✨ Identify</button>
      <a class="btn secondary" href="/scan-food">🏷️ Scan Label</a>
    </div>

    <div style="margin-top:10px;">
      <span class="pill" id="status">Waiting for photo…</span>
    </div>

    <div id="resultBox" style="display:none; margin-top:12px;">
      <div class="box">
        <div class="muted"><b>Detected:</b> <span id="foodName"></span> <span class="muted" id="conf"></span></div>
        <div class="muted" id="alts" style="margin-top:6px;"></div>
      </div>

      <div style="margin-top:10px;">
        <label class="muted">Portion</label>
        <select id="portion">
          <option value="1 small">1 small</option>
          <option value="1 medium" selected>1 medium</option>
          <option value="1 large">1 large</option>
          <option value="100 g">100 g</option>
          <option value="200 g">200 g</option>
        </select>
      </div>

      <form id="logFoodForm" method="post" action="/log-food" style="margin-top:10px;">
        <input type="hidden" name="food_description" id="food_description" value="">
        <button class="btn" type="submit">➕ Log Food</button>
        <div class="muted" style="margin-top:8px;">We’ll prefill your log with the identified food + portion.</div>
      </form>
    </div>
  </div>

  <script>
    const foodPhoto = document.getElementById("foodPhoto");      // camera capture (native)
    const foodUpload = document.getElementById("foodUpload");    // library upload
    const btnStartCam = document.getElementById("btnStartCam");
    const btnUpload = document.getElementById("btnUpload");

    const btnIdentify = document.getElementById("btnIdentify");
    const preview = document.getElementById("preview");
    const status = document.getElementById("status");

    const resultBox = document.getElementById("resultBox");
    const foodName = document.getElementById("foodName");
    const conf = document.getElementById("conf");
    const alts = document.getElementById("alts");
    const portion = document.getElementById("portion");
    const food_description = document.getElementById("food_description");
    const logFoodForm = document.getElementById("logFoodForm");

    let lastResult = null;

    function setStatus(t){ status.textContent = t; }

    btnStartCam.addEventListener("click", () => {
      // must be a user gesture for iOS; button click is perfect
      foodPhoto.value = "";
      foodPhoto.click();
    });

    btnUpload.addEventListener("click", () => {
      foodUpload.value = "";
      foodUpload.click();
    });

    function handleSelectedFile(file){
      lastResult = null;
      resultBox.style.display = "none";
      if (!file){
        preview.src = "";
        preview.style.display = "none";
        btnIdentify.disabled = true;
        return;
      }
      preview.src = URL.createObjectURL(file);
      preview.style.display = "block";
      btnIdentify.disabled = false;
    }

    foodPhoto.addEventListener("change", () => handleSelectedFile(foodPhoto.files && foodPhoto.files[0]));
    foodUpload.addEventListener("change", () => handleSelectedFile(foodUpload.files && foodUpload.files[0]));

    btnIdentify.addEventListener("click", async () => {
      const file = (foodPhoto.files && foodPhoto.files[0]) || (foodUpload.files && foodUpload.files[0]);
      if (!file) return;

      btnIdentify.disabled = true;
      setStatus("Identifying…");

      try{
        const fd = new FormData();
        fd.append("photo", file);

        const r = await fetch("/api/food-photo-identify", {
          method: "POST",
          body: fd
        });

        const j = await r.json();
        if (!r.ok || j.error){
          console.error(j);
          alert("Identify failed: " + (j.error || "unknown"));
          setStatus("Identify failed.");
          return;
        }
        lastResult = j;
        foodName.textContent = j.name || "Unknown";
        conf.textContent = (typeof j.confidence === "number") ? ` (confidence ${(j.confidence*100).toFixed(0)}%)` : "";
        alts.textContent = (j.alternatives && j.alternatives.length) ? ("Alternatives: " + j.alternatives.join(", ")) : "";
        resultBox.style.display = "block";
        setStatus("Review and log.");
      }catch(e){
        console.error(e);
        alert("Identify failed. Try again.");
        setStatus("Identify failed.");
      }finally{
        btnIdentify.disabled = false;
      }
    });

    logFoodForm.addEventListener("submit", () => {
      const name = (lastResult && lastResult.name) ? lastResult.name : "food";
      const p = portion.value || "1 serving";
      food_description.value = `${name} — ${p}`;
    });
  </script>
</body>
</html>"""
    return render_template_string(html)


@app.route("/api/food-photo-identify", methods=["POST"])
@login_required
def api_food_photo_identify():
    """Identify food from an uploaded photo, estimate macros, and optionally save."""
    if "photo" not in request.files:
        return jsonify({"ok": False, "error": "No photo uploaded"}), 400

    f = request.files["photo"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400

    raw = f.read()
    if not raw:
        return jsonify({"ok": False, "error": "Empty file"}), 400

    # Preprocess to improve OCR/handwriting and fix iPhone rotation
    data = _preprocess_for_vision(raw)
    fingerprint = _fingerprint_bytes(data)

    mime = f.mimetype or "image/jpeg"
    img_b64 = base64.b64encode(data).decode("utf-8")

    # 1) Identify the food (OpenAI vision)
    ident = _openai_identify_food_from_image(img_b64, mime_type=mime)
    if "error" in ident:
        return jsonify({"ok": False, "error": ident.get("error"), "details": ident.get("details"), "raw": ident.get("raw")}), 500

    name = (ident.get("name") or "").strip()
    confidence = ident.get("confidence")
    alternatives = ident.get("alternatives") or []
    notes = ident.get("notes") or ""

    # If user has previously corrected this exact image/label, reuse it
    try:
        u = get_current_user()
        if u:
            db = get_session(db_url)
            try:
                corr = db.query(ScanCorrection).filter_by(user_id=u.id, scan_type="food", fingerprint=fingerprint).first()
                if corr and corr.corrected:
                    name = corr.corrected.strip()
                    notes = (notes + " (used saved correction)").strip()
                    confidence = 0.99
            finally:
                db.close()
    except Exception:
        pass

    if not name:
        return jsonify({"ok": False, "error": "Could not identify food"}), 500

    # 2) Lookup macros
    # If a nutrition label is readable, prefer label-derived macros (helps differentiate diet/zero variants).
    nutrition = ident.get("nutrition") if isinstance(ident, dict) else None
    macros = None
    if nutrition and isinstance(nutrition, dict):
        try:
            macros = {
                "calories": float(nutrition.get("calories")) if nutrition.get("calories") is not None else None,
                "protein": float(nutrition.get("protein_g")) if nutrition.get("protein_g") is not None else None,
                "carbs": float(nutrition.get("carbs_g")) if nutrition.get("carbs_g") is not None else None,
                "fat": float(nutrition.get("fat_g")) if nutrition.get("fat_g") is not None else None,
                "serving_size_g": None,
                "matched_description": nutrition.get("serving_desc") or "nutrition label",
                "source": "label_ocr",
            }
            # If any key is missing, fall back to USDA
            if any(macros[k] is None for k in ("calories", "protein", "carbs", "fat")):
                macros = None
        except Exception:
            macros = None

    if macros is None:
        macros = _usda_lookup_macros(name)
    if "error" in macros:
        # Still return identification even if macros fail
        out = {
            "ok": True,
            "name": name,
            "food_name": name,
            "item": name,  # compatibility with older templates
            "confidence": confidence,
            "alternatives": alternatives,
            "notes": notes,
            "fingerprint": fingerprint,
            "macros": {"source": None},
            "macro_error": macros.get("error"),
        }
        return jsonify(out), 200

    out = {
        "ok": True,
        "name": name,
        "food_name": name,
        "item": name,
        "confidence": confidence,
        "alternatives": alternatives,
        "notes": notes,
        "fingerprint": fingerprint,
        "calories": macros.get("calories"),
        "protein": macros.get("protein"),
        "carbs": macros.get("carbs"),
        "fat": macros.get("fat"),
        "serving_size_g": macros.get("serving_size_g"),
        "matched_description": macros.get("matched_description"),
        "source": macros.get("source"),
        # structure expected by scan_food.html
        "macros": {
            "calories": macros.get("calories") or 0,
            "protein": macros.get("protein") or 0,
            "carbs": macros.get("carbs") or 0,
            "fat": macros.get("fat") or 0,
            "fiber": 0,
            "source": macros.get("source") or "usda",
        },
    }

    # 3) Optional auto-save (default ON for scanner)
    autosave = request.args.get("autosave", "1") == "1"
    if autosave:
        u = get_current_user()
        if u:
            try:
                db = get_session(db_url)
                try:
                    food_log = FoodLog(
                        user_id=u.id,
                        description=name,
                        total_calories=out.get("calories") or 0,
                        total_protein_g=out.get("protein") or 0,
                        total_fat_g=out.get("fat") or 0,
                        total_carbs_g=out.get("carbs") or 0,

                        food_name=name,
                        calories=out.get("calories"),
                        protein_g=out.get("protein"),
                        carbs_g=out.get("carbs"),
                        fat_g=out.get("fat"),
                        serving_size_g=out.get("serving_size_g"),
                        source=out.get("source"),
                        confidence=float(confidence) if confidence is not None else None,
                        fingerprint=fingerprint,
                        raw_text=(ident.get("raw") or ident.get("text") or "")[:2000] if isinstance(ident, dict) else None,
                        alternatives_json=json.dumps(alternatives)[:2000] if alternatives else None,
                        notes=(notes or "")[:500] if notes else None,

                        raw_data=json.dumps({"ident": ident, "macros": macros})[:5000],
                    )
                    db.add(food_log)
                    db.commit()
                    out["saved"] = True
                    out["food_log_id"] = food_log.id
                finally:
                    db.close()
            except Exception as e:
                out["saved"] = False
                out["save_error"] = str(e)

    return jsonify(out), 200

@app.route("/scan-food", methods=["GET"])
@login_required
def scan_food():
    """Legacy food scan entrypoint.

    We keep this route so old links/buttons keep working, but the
    actual Phase 1 scanner lives at /scan-nutrition and uses a native
    camera file input for best iPhone Safari compatibility.
    """
    # Preserve the autocam query param (if present)
    autocam = request.args.get("autocam")
    if autocam:
        return redirect(url_for("scan_nutrition", autocam=autocam))
    return redirect(url_for("scan_nutrition"))


@app.route("/scan-nutrition", methods=["GET"])
@login_required
def scan_nutrition():
    """
    Alias route used by the navbar.
    Should open the native-camera-based food scan (works best on iPhone Safari).
    """
    autocam = request.args.get("autocam") == "1"
    # Phase 1: use native camera capture via <input type=file capture="environment">
    # This is the most reliable behavior on iPhone Safari.
    return render_template("scan_food.html", autocam=autocam)

@app.post("/api/food-log/<int:food_log_id>/update")
@login_required
def api_update_food_log(food_log_id: int):
    """Allow users to correct/override macros after scan."""
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    def _f(x):
        try:
            return float(x)
        except Exception:
            return None

    db = get_session(db_url)
    try:
        log = db.query(FoodLog).filter_by(id=food_log_id, user_id=user.id).first()
        if not log:
            return jsonify({"error": "Not found"}), 404

        name = (payload.get("food_name") or payload.get("name") or "").strip()
        if name:
            log.food_name = name[:200]
            log.description = name[:500]

        calories = _f(payload.get("calories"))
        protein = _f(payload.get("protein"))
        carbs = _f(payload.get("carbs"))
        fat = _f(payload.get("fat"))

        # Update normalized fields
        if calories is not None:
            log.calories = calories
            log.total_calories = calories
        if protein is not None:
            log.protein_g = protein
            log.total_protein_g = protein
        if carbs is not None:
            log.carbs_g = carbs
            log.total_carbs_g = carbs
        if fat is not None:
            log.fat_g = fat
            log.total_fat_g = fat

        log.source = (payload.get("source") or log.source or "manual_edit")[:50]

        db.commit()
        return jsonify({
            "success": True,
            "food_log_id": log.id,
            "food_name": log.food_name or log.description,
            "calories": log.calories if log.calories is not None else log.total_calories,
            "protein": log.protein_g if log.protein_g is not None else log.total_protein_g,
            "carbs": log.carbs_g if log.carbs_g is not None else log.total_carbs_g,
            "fat": log.fat_g if log.fat_g is not None else log.total_fat_g,
            "source": log.source,
        })
    finally:
        db.close()

@app.post("/api/scan-correction")
@login_required
def api_scan_correction():
    """Store a per-user correction so future scans get it right instantly."""
    payload = request.get_json(silent=True) or {}
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    scan_type = (payload.get("scan_type") or "").strip()
    fingerprint = (payload.get("fingerprint") or "").strip()
    corrected = (payload.get("corrected") or "").strip()
    original = (payload.get("original") or "").strip()

    if scan_type not in ("peptide", "food"):
        return jsonify({"error": "invalid scan_type"}), 400
    if not fingerprint or not corrected:
        return jsonify({"error": "fingerprint and corrected required"}), 400

    db = get_session(db_url)
    try:
        row = db.query(ScanCorrection).filter_by(
            user_id=user.id,
            scan_type=scan_type,
            fingerprint=fingerprint
        ).first()
        if row:
            row.corrected = corrected[:200]
            row.original = original[:400]
        else:
            row = ScanCorrection(
                user_id=user.id,
                scan_type=scan_type,
                fingerprint=fingerprint,
                corrected=corrected[:200],
                original=original[:400] if original else None,
            )
            db.add(row)
        db.commit()
        return jsonify({"success": True})
    finally:
        db.close()

@app.route("/scan-peptides", methods=["GET"])
@login_required
def scan_peptides():
    """Phase 1: native-camera peptide label scan UI."""
    autocam = request.args.get("autocam") == "1"

    # Provide the full peptide library so the dropdown always offers every peptide
    all_peptides = []
    try:
        from database import PeptideDB  # type: ignore
        db = get_session(db_url)
        try:
            pdb = PeptideDB(db)
            peptides_list = getattr(pdb, "list_peptides", lambda: [])() or []
        finally:
            db.close()

        def _get(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        for p in peptides_list:
            name = (_get(p, "name", "") or "").strip()
            pid = _get(p, "id", None)
            if name and pid is not None:
                all_peptides.append({"id": int(pid), "name": name})
    except Exception:
        app.logger.exception("Failed to load peptides for scan page")
        all_peptides = []

    return render_template("scan_peptides.html", autocam=autocam, all_peptides=all_peptides)



@app.route("/scan-equipment", methods=["GET"])
@login_required
def scan_equipment():
    """Phase 1.5: native-camera gym equipment scan UI (category-level MVP)."""
    autocam = request.args.get("autocam") == "1"
    return render_template("scan_equipment.html", autocam=autocam, categories=_EQUIPMENT_CATEGORIES)

@app.route("/api/scan-equipment", methods=["POST"])
@login_required
def api_scan_equipment():
    """Accept an image and return an equipment CATEGORY suggestion."""
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    f = request.files["image"]
    image_bytes = f.read() or b""
    if not image_bytes:
        return jsonify({"error": "Empty image"}), 400

    mime = f.mimetype or "image/jpeg"
    # reuse the same best-effort preprocessing as other scans
    try:
        pre = _preprocess_for_vision(image_bytes)
    except Exception:
        pre = image_bytes

    # base64 encode
    import base64
    b64 = base64.b64encode(pre).decode("ascii")

    result = _openai_identify_equipment_from_image(b64, mime_type=mime)
    if result.get("error"):
        return jsonify(result), 400

    # Persist scan (for future training / analytics)
    try:
        db = get_session(db_url)
        try:
            scan = EquipmentScan(
                user_id=current_user.id,
                image_sha=_fingerprint_bytes(image_bytes),
                predicted_category=result.get("category"),
                confidence=float(result.get("confidence") or 0),
                alternatives_json=json.dumps(result.get("alternatives") or []),
                notes=(result.get("notes") or "")[:300],
            )
            db.add(scan)
            db.commit()
            scan_id = scan.id
        finally:
            db.close()
    except Exception:
        app.logger.exception("Failed to save equipment scan")
        scan_id = None

    return jsonify({
        "scan_id": scan_id,
        "category": result.get("category"),
        "confidence": result.get("confidence"),
        "alternatives": result.get("alternatives") or [],
        "notes": result.get("notes") or "",
        "categories": _EQUIPMENT_CATEGORIES,
    })

@app.route("/log-workout", methods=["POST"])
@login_required
def log_workout():
    """Create a workout log entry from the scan page."""
    cat = _coerce_equipment_category(request.form.get("equipment_category"))
    exercise_name = (request.form.get("exercise_name") or "").strip()[:120] or None
    notes = (request.form.get("notes") or "").strip()[:300] or None

    def _to_int(v):
        try:
            v = (v or "").strip()
            return int(v) if v else None
        except Exception:
            return None

    def _to_float(v):
        try:
            v = (v or "").strip()
            return float(v) if v else None
        except Exception:
            return None

    sets = _to_int(request.form.get("sets"))
    reps = _to_int(request.form.get("reps"))
    weight = _to_float(request.form.get("weight"))

    try:
        db = get_session(db_url)
        try:
            row = WorkoutLog(
                user_id=current_user.id,
                equipment_category=cat,
                exercise_name=exercise_name,
                sets=sets,
                reps=reps,
                weight=weight,
                notes=notes,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()
        flash("Workout logged ✅", "success")
    except Exception:
        app.logger.exception("Failed to save workout log")
        flash("Could not save workout log. Please try again.", "danger")

    return redirect(url_for("training_log"))

@app.route("/training", methods=["GET"])
@login_required
def training_log():
    """Simple training log list (MVP)."""
    rows = []
    try:
        db = get_session(db_url)
        try:
            q = db.query(WorkoutLog).filter(WorkoutLog.user_id == current_user.id).order_by(WorkoutLog.performed_at.desc()).limit(50)
            rows = q.all()
        finally:
            db.close()
    except Exception:
        app.logger.exception("Failed to load workout logs")
        rows = []
    return render_template("training_log.html", rows=rows, categories=_EQUIPMENT_CATEGORIES)

@app.route("/api/scan-peptide-label", methods=["POST"])
@login_required
def api_scan_peptide_label():
    """Accepts an image and returns OCR + best peptide name matches."""
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    f = request.files["image"]
    raw = f.read()
    if not raw:
        return jsonify({"error": "Empty file"}), 400

    data = _preprocess_for_vision(raw)
    fingerprint = _fingerprint_bytes(data)

    mime = f.mimetype or "image/jpeg"
    img_b64 = base64.b64encode(data).decode("utf-8")

    peptides = _load_peptides_list()
    peptide_names = [p.get("name", "") for p in peptides if isinstance(p, dict) and p.get("name")]

    # If user already corrected this exact label, return it immediately
    user = get_current_user()
    if user:
        db = get_session(db_url)
        try:
            corr = db.query(ScanCorrection).filter_by(user_id=user.id, scan_type="peptide", fingerprint=fingerprint).first()
            if corr and corr.corrected:
                return jsonify({
                    "fingerprint": fingerprint,
                    "raw_text": corr.original or "",
                    "matches": [{"name": corr.corrected, "confidence": 0.99}],
                    "notes": "used saved correction"
                }), 200
        finally:
            db.close()

    result = _openai_scan_peptide_label(img_b64, peptide_names=peptide_names, mime_type=mime)
    if "error" in result:
        return jsonify(result), 500

    raw_text = (result.get("text") or result.get("raw_text") or "").strip()
    candidates = []
    for k in ("peptides", "candidates"):
        v = result.get(k)
        if isinstance(v, list):
            candidates.extend([str(x) for x in v if x])
    if raw_text:
        # pull obvious tokens like "TB500", "BPC 157" etc
        tokens = re.findall(r"[A-Za-z0-9\-\+]{2,}", raw_text)
        candidates.extend(tokens)

    # Detect mg amount (best-effort) from raw_text
    vial_mg = None
    if raw_text:
        mm = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", raw_text, re.IGNORECASE)
        if mm:
            try:
                vial_mg = float(mm.group(1))
            except Exception:
                vial_mg = None

# Rank against known peptide list
    matches = _best_peptide_matches(candidates, peptide_names, limit=5)

    out = {
        "fingerprint": fingerprint,
        "raw_text": raw_text,
        "matches": matches,
        "notes": (result.get("notes") or "").strip(),
        "vial_mg": vial_mg,
    }
    return jsonify(out), 200



@app.post("/api/save-scanned-peptide")
@login_required
def api_save_scanned_peptide():
    """Create one or more vials from a scan result so the user doesn't have to type.

    Uses the existing PeptideDB helper (same mechanism as /add-vial).
    Returns JSON always (even on errors) so the mobile UI never displays HTML.
    """
    try:
        payload = request.get_json(silent=True) or {}
        peptide_name = (payload.get("peptide_name") or payload.get("name") or "").strip()
        if not peptide_name:
            return jsonify({"error": "peptide_name required"}), 400

        def _f(x):
            try:
                return float(x)
            except Exception:
                return None

        def _i(x, default=1):
            try:
                v = int(str(x).strip())
                return v
            except Exception:
                return default

        vial_size_mg = _f(payload.get("vial_size_mg")) or 0.0
        bac_water_ml = _f(payload.get("bac_water_ml"))
        notes = (payload.get("notes") or payload.get("raw_text") or "")[:300]

        num_vials = _i(payload.get("num_vials") or payload.get("number_of_vials") or 1, default=1)
        if num_vials < 1:
            num_vials = 1
        if num_vials > 50:
            num_vials = 50  # safety

        # Find peptide_id by name (case-insensitive) using PeptideDB list
        try:
            from database import PeptideDB  # type: ignore
        except Exception as e:
            return jsonify({"error": f"Database helper not available: {e}"}), 500

        db = get_session(db_url)
        try:
            pdb = PeptideDB(db)
            _seed_peptides_if_empty(pdb)

            peptides = getattr(pdb, "list_peptides", lambda: [])()
            peptide_id = None

            # Normalize incoming name (strip confidence like "BPC-157 (100%)")
            peptide_name_clean = re.sub(r"\s*\(.*?\)\s*$", "", peptide_name).strip()

            def _get(obj, key, default=None):
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)

            def _norm(s: str) -> str:
                s = (s or "").strip().lower()
                s = s.replace("—","-").replace("–","-").replace("_","-")
                s = re.sub(r"\s+", " ", s)
                # common aliases
                s = s.replace("bpc 157","bpc-157").replace("bpc157","bpc-157")
                s = s.replace("tb500","tb-500").replace("tb 500","tb-500")
                s = s.replace("pt141","pt-141").replace("pt 141","pt-141")
                s = s.replace("mt2","mt-2").replace("mt 2","mt-2")
                s = s.replace("semiglutide","semaglutide")
                return s

            target = _norm(peptide_name_clean)

            for p in peptides or []:
                try:
                    pname = _get(p, "name", "") or _get(p, "common_name", "") or ""
                    if _norm(pname) == target:
                        pid = _get(p, "id", None)
                        if pid is not None:
                            peptide_id = int(pid)
                            break
                except Exception:
                    continue

            # Create peptide if missing (best-effort)
            if peptide_id is None:
                add_pep = getattr(pdb, "add_peptide", None)
                if callable(add_pep):
                    try:
                        # try common signatures
                        try:
                            add_pep(name=peptide_name_clean, common_name=None)
                        except TypeError:
                            add_pep(peptide_name_clean)
                        db.commit()
                    except Exception:
                        # if add fails, continue to error below
                        pass

                    peptides = getattr(pdb, "list_peptides", lambda: [])()
                    for p in peptides or []:
                        try:
                            pname = _get(p, "name", "") or _get(p, "common_name", "") or ""
                            if _norm(pname) == target:
                                pid = _get(p, "id", None)
                                if pid is not None:
                                    peptide_id = int(pid)
                                    break
                        except Exception:
                            continue

            if peptide_id is None:
                return jsonify({"error": f"peptide_not_found: {peptide_name_clean}"}), 400

            add_vial = getattr(pdb, "add_vial", None)
            if not callable(add_vial):
                return jsonify({"error": "Database helper does not implement add_vial()"}), 500

            for _ in range(num_vials):
                add_vial(
                    peptide_id=peptide_id,
                    mg_amount=float(vial_size_mg),
                    bacteriostatic_water_ml=bac_water_ml,
                    purchase_date=datetime.utcnow(),
                    reconstitution_date=datetime.utcnow(),
                    lot_number=None,
                    vendor=None,
                    cost=None,
                    notes=notes or None,
                )
            db.commit()

            # Best-effort: if helper provides list_active_vials, try to get latest id
            vial_id = None
            try:
                vials = getattr(pdb, "list_active_vials", None)
                if callable(vials):
                    vv = vials()
                    if vv:
                        vial_id = getattr(vv[-1], "id", None) or (vv[-1].get("id") if isinstance(vv[-1], dict) else None)
            except Exception:
                vial_id = None

            return jsonify({
                "success": True,
                "created": num_vials,
                "vial_id": vial_id,
                "peptide_name": peptide_name,
                "vial_size_mg": vial_size_mg,
            }), 200
        finally:
            try:
                db.close()
            except Exception:
                pass

    except Exception as e:
        app.logger.exception("api_save_scanned_peptide failed")
        return jsonify({"error": "save_failed", "details": str(e)[:500]}), 500
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_if_exists("index.html", fallback_endpoint="register")

# -----------------------------------------------------------------------------
# Medical Disclaimer
# -----------------------------------------------------------------------------
@app.route("/medical-disclaimer")
def medical_disclaimer():
    """Medical disclaimer page (linked from the global banner)."""
    return render_if_exists("medical_disclaimer.html", fallback_endpoint="index")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not username or not email or not password:
            flash("All fields are required.", "error")
            return render_if_exists("register.html", fallback_endpoint="index")

        db = get_session(db_url)
        try:
            existing = db.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()
            if existing:
                flash("Username or email already exists.", "error")
                return render_if_exists("register.html", fallback_endpoint="index")

            user = User(username=username, email=email, tier="free")
            user.set_password(password)
            db.add(user)
            db.commit()
            session["user_id"] = user.id
            flash("Welcome! You're all set.", "success")
            return redirect(url_for("dashboard"))
        finally:
            db.close()

    return render_if_exists("register.html", fallback_endpoint="index")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not username or not password:
            flash("Username and password required.", "error")
            return render_if_exists("login.html", fallback_endpoint="index")

        db = get_session(db_url)
        try:
            user = db.query(User).filter_by(username=username).first()
            if not user or not user.check_password(password):
                flash("Invalid credentials.", "error")
                return render_if_exists("login.html", fallback_endpoint="index")

            session["user_id"] = user.id
            flash("Logged in!", "success")
            return redirect(url_for("dashboard"))
        finally:
            db.close()

    return render_if_exists("login.html", fallback_endpoint="index")

@app.route("/logout")
def logout():
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
@require_onboarding
def dashboard():
    stats, protocols, recent_injections = _compute_dashboard_context()
    profile = get_user_profile(session["user_id"])

    # Recent food logs (best-effort)
    food_logs = []
    food_totals_today = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
    try:
        u = get_current_user()
        if u:
            db = get_session(db_url)
            try:
                # last 20 entries
                food_logs = (
                    db.query(FoodLog)
                    .filter(FoodLog.user_id == u.id)
                    .order_by(FoodLog.timestamp.desc())
                    .limit(20)
                    .all()
                )
                # today totals (server timezone)
                from datetime import date
                today = date.today()
                todays = (
                    db.query(FoodLog)
                    .filter(FoodLog.user_id == u.id)
                    .filter(func.date(FoodLog.timestamp) == today)
                    .all()
                )
                for r in todays:
                    food_totals_today["calories"] += float(r.total_calories or 0)
                    food_totals_today["protein"] += float(r.total_protein_g or 0)
                    food_totals_today["carbs"] += float(r.total_carbs_g or 0)
                    food_totals_today["fat"] += float(r.total_fat_g or 0)
                # round
                for k in food_totals_today:
                    food_totals_today[k] = round(food_totals_today[k], 1)
            finally:
                db.close()
    except Exception as e:
        print(f"Food logs dashboard fallback (non-fatal): {e}")


    # Active vials preview for dashboard (visual fill estimate)
    active_vials_preview = []
    try:
        u = get_current_user()
        if u:
            from database import PeptideDB  # type: ignore
            db = get_session(db_url)
            try:
                pdb = PeptideDB(db)
                vials = getattr(pdb, "list_active_vials", lambda: [])() or []
            finally:
                db.close()

            def _get(obj, key, default=None):
                if isinstance(obj, dict):
                    return obj.get(key, default)
                return getattr(obj, key, default)

            def _to_float(x):
                try:
                    return float(x)
                except Exception:
                    return None

            for v in (vials[:6] if isinstance(vials, list) else []):
                name = (_get(v, "peptide_name", None) or _get(v, "peptide", None) or _get(v, "name", None) or "").strip()
                vial_id = _get(v, "id", None)

                total_mg = _to_float(_get(v, "vial_size_mg", None) or _get(v, "total_mg", None) or _get(v, "amount_mg", None))
                remaining_mg = _to_float(_get(v, "remaining_mg", None) or _get(v, "mg_remaining", None) or _get(v, "remaining", None))

                pct = None
                if total_mg and remaining_mg is not None:
                    try:
                        pct = max(0.0, min(1.0, remaining_mg / total_mg))
                    except Exception:
                        pct = None

                active_vials_preview.append({
                    "id": vial_id,
                    "name": name,
                    "total_mg": total_mg,
                    "remaining_mg": remaining_mg,
                    "pct": pct,
                })
    except Exception as e:
        print(f"Active vials preview fallback (non-fatal): {e}")

    return render_if_exists(
        "dashboard.html",
        fallback_endpoint="index",
        stats=stats,
        protocols=protocols,
        recent_injections=recent_injections,
        profile=profile,
        food_logs=food_logs,
        food_totals_today=food_totals_today,
        active_vials_preview=active_vials_preview,
    )


# -----------------------------------------------------------------------------
# Password Reset Routes
# -----------------------------------------------------------------------------
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Request password reset"""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        
        if not email:
            flash("Please enter your email address.", "error")
            return render_if_exists("forgot_password.html", fallback_endpoint="login")
        
        db = get_session(db_url)
        try:
            user = db.query(User).filter_by(email=email).first()
            
            if user:
                # Generate reset token
                token = secrets.token_urlsafe(32)
                expires_at = datetime.utcnow() + timedelta(hours=24)
                
                reset_token = PasswordResetToken(
                    user_id=user.id,
                    token=token,
                    expires_at=expires_at
                )
                db.add(reset_token)
                db.commit()
                
                # Create reset link
                reset_link = url_for('reset_password', token=token, _external=True)
                
                flash(f"Password reset link generated! Copy this link: {reset_link}", "success")
                flash("This link expires in 24 hours.", "info")
            else:
                # Don't reveal if email exists
                flash("If that email is registered, a reset link has been generated.", "info")
        finally:
            db.close()
    
    return render_if_exists("forgot_password.html", fallback_endpoint="login")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Reset password using token"""
    db = get_session(db_url)
    try:
        # Find valid token
        reset_token = db.query(PasswordResetToken).filter_by(
            token=token,
            used=0
        ).first()
        
        if not reset_token:
            flash("Invalid or expired reset link.", "error")
            return redirect(url_for("login"))
        
        if reset_token.expires_at < datetime.utcnow():
            flash("This reset link has expired.", "error")
            return redirect(url_for("login"))
        
        user = db.query(User).filter_by(id=reset_token.user_id).first()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("login"))
        
        if request.method == "POST":
            password = (request.form.get("password") or "").strip()
            confirm_password = (request.form.get("confirm_password") or "").strip()
            
            if not password or not confirm_password:
                flash("Both password fields are required.", "error")
                return render_if_exists("reset_password.html", fallback_endpoint="login", token=token)
            
            if password != confirm_password:
                flash("Passwords do not match.", "error")
                return render_if_exists("reset_password.html", fallback_endpoint="login", token=token)
            
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return render_if_exists("reset_password.html", fallback_endpoint="login", token=token)
            
            # Update password
            user.set_password(password)
            
            # Mark token as used
            reset_token.used = 1
            
            db.commit()
            
            flash("Password reset successful! You can now log in.", "success")
            return redirect(url_for("login"))
        
        return render_if_exists("reset_password.html", fallback_endpoint="login", token=token, email=user.email)
    
    finally:
        db.close()

# -----------------------------------------------------------------------------
# User Profile Routes
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# Profile Skip (optional onboarding)
# -----------------------------------------------------------------------------
@app.route("/profile-skip", methods=["GET"])
@login_required
def profile_skip():
    """Allow users to skip profile setup and continue to dashboard."""
    session["profile_skipped"] = True
    flash("Profile skipped — you can complete it later.", "info")
    return redirect(url_for("dashboard"))

# Alias endpoints (in case templates reference different names)
@app.route("/profile/skip", methods=["GET"], endpoint="skip_profile")
@login_required
def _skip_profile_alias():
    session["profile_skipped"] = True
    flash("Profile skipped — you can complete it later.", "info")
    return redirect(url_for("dashboard"))

@app.route("/profile-setup", methods=["GET", "POST"])
@login_required
def profile_setup():
    """User profile setup/edit page"""
    db = get_session(db_url)
    try:
        profile = db.query(UserProfile).filter_by(user_id=session["user_id"]).first()
        
        if request.method == "POST":
            age = request.form.get("age")
            weight_lbs = request.form.get("weight_lbs")
            height_inches = request.form.get("height_inches")
            gender = request.form.get("gender")
            goals = request.form.getlist("goals")
            experience_level = request.form.get("experience_level")
            medical_notes = request.form.get("medical_notes", "").strip()
            
            if not all([age, weight_lbs, height_inches, gender, experience_level]):
                flash("Please fill in all required fields.", "error")
                return render_if_exists("profile_setup.html", fallback_endpoint="dashboard", profile=profile)
            
            if not goals:
                flash("Please select at least one goal.", "error")
                return render_if_exists("profile_setup.html", fallback_endpoint="dashboard", profile=profile)
            
            if profile:
                profile.age = int(age)
                profile.weight_lbs = float(weight_lbs)
                profile.height_inches = int(height_inches)
                profile.gender = gender
                profile.goals = json.dumps(goals)
                profile.experience_level = experience_level
                profile.medical_notes = medical_notes
                profile.completed_at = datetime.utcnow()
                profile.updated_at = datetime.utcnow()
                flash("Profile updated successfully!", "success")
            else:
                profile = UserProfile(
                    user_id=session["user_id"],
                    age=int(age),
                    weight_lbs=float(weight_lbs),
                    height_inches=int(height_inches),
                    gender=gender,
                    goals=json.dumps(goals),
                    experience_level=experience_level,
                    medical_notes=medical_notes,
                    completed_at=datetime.utcnow()
                )
                db.add(profile)
                flash("Profile created successfully!", "success")
            
            db.commit()
            return redirect(url_for("dashboard"))
        
        return render_if_exists("profile_setup.html", fallback_endpoint="dashboard", profile=profile)
        
    finally:
        db.close()


def get_user_profile(user_id):
    """Helper function to get user profile"""
    db = get_session(db_url)
    try:
        return db.query(UserProfile).filter_by(user_id=user_id).first()
    finally:
        db.close()



@app.get("/onboarding/step-1")
def onboarding_step_1():
    # Alias route for the dashboard banner buttons
    return redirect(url_for("profile_setup"))

@app.route("/onboarding/step-2", methods=["GET", "POST"])
def onboarding_step_2():
    u = get_current_user()
    if not u:
        return redirect(url_for("login"))

    # Profile is optional; do not force step 1.
    if request.method == "POST":
        db = get_session(db_url)
        try:
            existing = db.query(DisclaimerAcceptance).filter_by(user_id=u.id).first()
            if not existing:
                db.add(DisclaimerAcceptance(user_id=u.id, accepted_at=datetime.utcnow()))
            db.commit()
        finally:
            db.close()
        flash("Thanks — disclaimer acknowledged.", "success")
        return redirect(url_for("dashboard"))

    # Render a dedicated template if you add one; otherwise fall back to medical_disclaimer.html
    try:
        return render_template("onboarding_disclaimer.html", title="Disclaimer Acknowledgement")
    except TemplateNotFound:
        # We pass a flag so your template can show an "I Understand" button if you choose
        return render_template("medical_disclaimer.html", title="Medical Disclaimer", show_accept=True)

# -----------------------------------------------------------------------------
# Stub endpoints to prevent BuildError
# -----------------------------------------------------------------------------
@app.route("/log-injection", methods=["GET", "POST"])
@login_required
def log_injection():
    if request.method == "POST":
        flash("log_injection is not wired yet (stub).", "info")
        return redirect(url_for("dashboard"))
    return render_if_exists("log_injection.html", fallback_endpoint="dashboard")

@app.route("/add-vial", methods=["GET", "POST"])
@login_required
def add_vial():
    peptides = _load_peptides_list()

    if request.method == "POST":
        peptide_id = (request.form.get("peptide_id") or "").strip()
        mg_amount = (request.form.get("mg_amount") or "").strip()
        vendor = (request.form.get("vendor") or "").strip()
        lot_number = (request.form.get("lot_number") or "").strip()
        reconstitute = (request.form.get("reconstitute") or "no").strip()
        ml_water = (request.form.get("ml_water") or "").strip()
        reconstitution_date_str = (request.form.get("reconstitution_date") or "").strip()

        if not peptide_id or not mg_amount:
            flash("Please select a peptide and enter the vial amount (mg).", "warning")
            return render_if_exists("add_vial.html", fallback_endpoint="dashboard", peptides=peptides)

        try:
            from database import PeptideDB  # type: ignore

            db = get_session(db_url)
            try:
                pdb = PeptideDB(db)
                # Ensure peptides exist (fresh DB on Render)
                _seed_peptides_if_empty(pdb)

                add_fn = getattr(pdb, "add_vial", None)
                if not callable(add_fn):
                    raise RuntimeError("Database helper does not implement add_vial().")

                purchase_date = datetime.utcnow()
                if reconstitute == "yes":
                    if reconstitution_date_str:
                        # datetime-local comes in as "YYYY-MM-DDTHH:MM" (no timezone)
                        reconstitution_date = datetime.fromisoformat(reconstitution_date_str)
                    else:
                        reconstitution_date = datetime.utcnow()
                else:
                    reconstitution_date = None
                bacteriostatic_water_ml = float(ml_water) if ml_water else None

                add_fn(
                    peptide_id=int(peptide_id),
                    mg_amount=float(mg_amount),
                    bacteriostatic_water_ml=bacteriostatic_water_ml,
                    purchase_date=purchase_date,
                    reconstitution_date=reconstitution_date,
                    lot_number=lot_number or None,
                    vendor=vendor or None,
                    cost=None,
                    notes=None,
                )
                db.commit()
                flash("Vial added.", "success")
                return redirect(url_for("vials"))
            finally:
                db.close()

        except Exception as e:
            app.logger.exception("Failed to add vial")
            flash(f"Could not add vial: {e}", "error")
            return render_if_exists("add_vial.html", fallback_endpoint="dashboard", peptides=peptides)

    return render_if_exists("add_vial.html", fallback_endpoint="dashboard", peptides=peptides)



@app.route("/add-protocol", methods=["GET", "POST"])
@login_required
def add_protocol():
    peptides = _load_peptides_list()

    # One-click templates: /add-protocol?template=epitalon
    template_key = (request.args.get("template") or "").strip().lower()
    template_data = PROTOCOL_TEMPLATES.get(template_key)

    if request.method == "POST":
        protocol_name = (request.form.get("protocol_name") or "").strip()
        peptide_id = (request.form.get("peptide_id") or "").strip()
        dose_mcg = (request.form.get("dose_mcg") or "").strip()
        frequency_per_day = (request.form.get("frequency_per_day") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        if not protocol_name:
            flash("Protocol name is required.", "warning")
            return render_if_exists(
                "add_protocol.html",
                fallback_endpoint="dashboard",
                peptides=peptides,
                template_key=template_key,
                template_data=template_data,
                form=request.form,
            )

        # Best-effort: persist via your project's DB helper if available.
        try:
            from database import PeptideDB  # type: ignore

            db = get_session(db_url)
            try:
                pdb = PeptideDB(db)
                create_fn = getattr(pdb, "create_protocol", None) or getattr(pdb, "add_protocol", None)
                if callable(create_fn):
                    create_fn(                        name=protocol_name,
                        peptide_id=int(peptide_id) if peptide_id else None,
                        dose_mcg=float(dose_mcg) if dose_mcg else None,
                        frequency_per_day=int(frequency_per_day) if frequency_per_day else None,
                        notes=notes or None,
                    )
                    db.commit()
                    flash("Protocol created.", "success")
                    return redirect(url_for("protocols"))
            finally:
                try:
                    db.close()
                except Exception:
                    pass
        except Exception:
            app.logger.exception("add_protocol persistence not available; using stub fallback.")

        flash("Protocol form submitted, but persistence is not wired yet.", "info")
        return redirect(url_for("dashboard"))

    # Pre-fill fields from template if present.
    prefill = {
        "protocol_name": template_data.get("protocol_name") if template_data else "",
        "peptide_common": template_data.get("name") if template_data else "",
    }

    return render_if_exists(
        "add_protocol.html",
        fallback_endpoint="dashboard",
        peptides=peptides,
        template_key=template_key,
        template_data=template_data,
        prefill=prefill,
    )


@app.route("/protocols/<int:protocol_id>")
@login_required
def protocol_detail(protocol_id: int):
    # Stub detail page; lets dashboard links render.
    return render_if_exists("protocol_detail.html", fallback_endpoint="protocols", protocol_id=protocol_id)

# -----------------------------------------------------------------------------
# Nutrition tracking with Calorie Ninja API (LEGACY - Keep for backward compatibility)
# -----------------------------------------------------------------------------
CALORIE_NINJA_API_KEY = os.environ.get("CALORIE_NINJA_API_KEY")

@app.route("/nutrition")
@login_required
@require_onboarding
def nutrition():
    """Nutrition dashboard - shows food logs and daily totals"""
    db = get_session(db_url)
    try:
        # Get today's food logs
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_logs = db.query(FoodLog).filter(
            FoodLog.user_id == session["user_id"],
            FoodLog.timestamp >= today_start
        ).order_by(FoodLog.timestamp.desc()).all()
        
        # Calculate daily totals
        daily_calories = sum(log.total_calories or 0 for log in today_logs)
        daily_protein = sum(log.total_protein_g or 0 for log in today_logs)
        daily_fat = sum(log.total_fat_g or 0 for log in today_logs)
        daily_carbs = sum(log.total_carbs_g or 0 for log in today_logs)
        
        # Get last 7 days
        week_ago = datetime.utcnow() - timedelta(days=7)
        week_logs = db.query(FoodLog).filter(
            FoodLog.user_id == session["user_id"],
            FoodLog.timestamp >= week_ago
        ).all()
        
        # Group by day
        daily_data = {}
        for log in week_logs:
            day_key = log.timestamp.strftime('%Y-%m-%d')
            if day_key not in daily_data:
                daily_data[day_key] = 0
            daily_data[day_key] += log.total_calories or 0
        
        return render_if_exists("nutrition.html", fallback_endpoint="dashboard",
                              today_logs=today_logs,
                              daily_calories=daily_calories,
                              daily_protein=daily_protein,
                              daily_fat=daily_fat,
                              daily_carbs=daily_carbs,
                              daily_data=daily_data)
    finally:
        db.close()

@app.route("/log-food", methods=["GET", "POST"])
@login_required
@require_onboarding
def log_food():
    """Log food entry using Calorie Ninja API"""
    if request.method == "POST":
        food_description = (request.form.get("food_description") or "").strip()
        
        if not food_description:
            flash("Please describe what you ate.", "warning")
            return redirect(url_for("log_food"))
        
        if not CALORIE_NINJA_API_KEY:
            flash("Nutrition API not configured. Please contact support.", "error")
            return redirect(url_for("log_food"))
        
        # Call Calorie Ninja API
        api_url = "https://api.calorieninjas.com/v1/nutrition?query="
        headers = {"X-Api-Key": CALORIE_NINJA_API_KEY}
        
        try:
            response = requests.get(
                api_url + food_description,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("items") and len(data["items"]) > 0:
                    # Calculate totals
                    total_calories = sum(item.get("calories", 0) for item in data["items"])
                    total_protein = sum(item.get("protein_g", 0) for item in data["items"])
                    total_fat = sum(item.get("fat_total_g", 0) for item in data["items"])
                    total_carbs = sum(item.get("carbohydrates_total_g", 0) for item in data["items"])
                    
                    # Save to database
                    db = get_session(db_url)
                    try:
                        food_log = FoodLog(                            description=food_description,
                            total_calories=total_calories,
                            total_protein_g=total_protein,
                            total_fat_g=total_fat,
                            total_carbs_g=total_carbs,
                            raw_data=json.dumps(data)
                        )
                        db.add(food_log)
                        db.commit()
                        flash(f"✓ Logged: {food_description} - {total_calories:.0f} calories", "success")
                        return redirect(url_for("nutrition"))
                    finally:
                        db.close()
                else:
                    flash("Could not find nutrition data. Try being more specific (e.g., '2 eggs and 1 slice of toast').", "warning")
            elif response.status_code == 401:
                flash("API key invalid. Please check configuration.", "error")
            else:
                flash(f"API Error: {response.status_code}. Please try again.", "error")
        
        except requests.exceptions.Timeout:
            flash("Request timed out. Please try again.", "error")
        except Exception as e:
            print(f"Calorie Ninja API error: {e}")
            flash("Error connecting to nutrition database. Please try again.", "error")
    
    return render_if_exists("log_food.html", fallback_endpoint="nutrition")

@app.route("/delete-food/<int:food_id>", methods=["POST"])
@login_required
def delete_food(food_id: int):
    """Delete a food log entry"""
    db = get_session(db_url)
    try:
        food_log = db.query(FoodLog).filter_by(
            id=food_id,
            user_id=session["user_id"]
        ).first()
        
        if food_log:
            db.delete(food_log)
            db.commit()
            flash("Food entry deleted.", "success")
    finally:
        db.close()
    
    return redirect(url_for("nutrition"))


@app.route("/api/log-food", methods=["POST"])
@login_required
@require_onboarding
def api_log_food():
    """API endpoint to log food from USDA data"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        
        description = data.get("description")
        total_calories = data.get("total_calories", 0)
        total_protein_g = data.get("total_protein_g", 0)
        total_carbs_g = data.get("total_carbs_g", 0)
        total_fat_g = data.get("total_fat_g", 0)
        
        if not description:
            return jsonify({"success": False, "error": "Description is required"}), 400
        
        db = get_session(db_url)
        try:
            food_log = FoodLog(
                user_id=get_current_user().id,
                description=description,
                total_calories=total_calories,
                total_protein_g=total_protein_g,
                total_fat_g=total_fat_g,
                total_carbs_g=total_carbs_g,
                raw_data=json.dumps(data)
            )
            db.add(food_log)
            db.commit()
            
            return jsonify({
                "success": True,
                "message": "Food logged successfully",
                "food_id": food_log.id
            })
        finally:
            db.close()
            
    except Exception as e:
        print(f"Error logging food: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -----------------------------------------------------------------------------
# Other common pages (safe)
# -----------------------------------------------------------------------------
@app.route("/peptides")
@login_required
@require_onboarding
def peptides():
    """Peptide library page.

    The template expects a `peptides` iterable (and optionally `peptides_json`).
    If your DB helper is unavailable, we still render the page with an empty list.
    """
    peptides_list: list[Any] = []
    peptides_json: str = "[]"

    try:
        from database import PeptideDB  # type: ignore

        db = get_session(db_url)
        pdb = PeptideDB(db)
        peptides_list = getattr(pdb, "list_peptides", lambda: [])()
    except Exception:
        app.logger.exception("Failed to load peptides from DB")

    try:
        payload = []
        for p in peptides_list:
            payload.append(
                {
                    "id": getattr(p, "id", None),
                    "name": getattr(p, "name", ""),
                    "category": getattr(p, "category", None),
                    "summary": getattr(p, "summary", "") or getattr(p, "description", "") or "",
                    "benefits": getattr(p, "benefits", "") or "",
                    # Optional gating fields if present in your DB model
                    "locked": bool(getattr(p, "locked", False) or getattr(p, "is_locked", False)),
                    "tier": getattr(p, "tier", None),
                }
            )
        peptides_json = json.dumps(payload)
    except Exception:
        app.logger.exception("Failed to serialize peptides")
        peptides_json = "[]"

    return render_if_exists(
        "peptides.html",
        peptides=peptides_list,
        peptides_json=peptides_json,
        fallback_endpoint="dashboard",
    )

@app.route("/api/peptides")
@login_required
def api_peptides():
    """JSON API used by the Peptides page/compare UI."""
    try:
        from database import PeptideDB  # type: ignore

        db = get_session(db_url)
        pdb = PeptideDB(db)
        peptides_list = getattr(pdb, "list_peptides", lambda: [])()
    except Exception:
        app.logger.exception("Failed to load peptides for API")
        peptides_list = []

    payload = []
    for p in peptides_list:
        payload.append(
            {
                "id": getattr(p, "id", None),
                "name": getattr(p, "name", ""),
                "category": getattr(p, "category", None),
                "summary": getattr(p, "summary", "") or getattr(p, "description", "") or "",
                "benefits": getattr(p, "benefits", "") or "",
                "locked": bool(getattr(p, "locked", False) or getattr(p, "is_locked", False)),
                "tier": getattr(p, "tier", None),
            }
        )
    return jsonify(payload)

# Backwards-compatible alias in case templates still reference url_for('pep_ai')
@app.route("/pep-ai")
@login_required
@require_onboarding
def pep_ai():
    return redirect(url_for("chat"))


@app.route("/calculator")
@login_required
@require_onboarding
def calculator():
    """Legacy route - redirects to peptide-calculator"""
    return redirect(url_for("peptide_calculator"))

@app.route("/peptide-calculator", methods=["GET", "POST"])
@login_required
@require_onboarding
def peptide_calculator():
    """
    Peptide Calculator:
    - GET: show calculator UI
    - POST: (optional) save a protocol using the entered values
    """

    # Prefer the project's DB helper if available; otherwise fall back to a safe empty list
    peptides = _load_peptides_list()

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "save_protocol":
            try:
                from database import PeptideDB  # type: ignore

                db_session = get_session(db_url)
                try:
                    pdb = PeptideDB(db_session)

                    peptide_id = int(request.form.get("peptide_id") or 0)
                    protocol_name = (request.form.get("protocol_name") or "").strip() or "New Protocol"
                    desired_dose_mcg = float(request.form.get("desired_dose_mcg") or 0)
                    injections_per_day = int(request.form.get("injections_per_day") or 1)

                    vial_size_mg = (request.form.get("vial_size_mg") or "").strip()
                    water_ml = (request.form.get("water_ml") or "").strip()

                    notes_bits = []
                    if vial_size_mg:
                        notes_bits.append(f"Vial size: {vial_size_mg} mg")
                    if water_ml:
                        notes_bits.append(f"Bacteriostatic water: {water_ml} ml")
                    notes_bits.append("Saved from Peptide Calculator.")
                    notes = " • ".join([b for b in notes_bits if b])

                    create_fn = getattr(pdb, "create_protocol", None) or getattr(pdb, "add_protocol", None)
                    if not callable(create_fn):
                        raise RuntimeError("Database helper does not implement create_protocol()/add_protocol().")

                    create_fn(
                        peptide_id=peptide_id,
                        name=protocol_name,
                        dose_mcg=desired_dose_mcg,
                        frequency_per_day=injections_per_day,
                        notes=notes,
                    )
                    db_session.commit()
                    flash("Protocol saved.", "success")
                    return redirect(url_for("protocols"))
                finally:
                    try:
                        db_session.close()
                    except Exception:
                        pass

            except Exception as e:
                app.logger.exception("Could not save protocol from calculator")
                flash(f"Could not save protocol: {e}", "danger")

    return render_template("calculator.html", peptides=peptides)

@app.route("/protocols")
@login_required
@require_onboarding
def protocols():
    return render_if_exists("protocols.html", fallback_endpoint="dashboard")

@app.route("/vials")
@login_required
@require_onboarding
def vials():
    return render_if_exists("vials.html", fallback_endpoint="dashboard")

@app.route("/history")
@login_required
@require_onboarding
def history():
    return render_if_exists("history.html", fallback_endpoint="dashboard")

@app.route("/coaching")
@login_required
def coaching():
    return render_if_exists("coaching.html", fallback_endpoint="dashboard")

@app.route("/chat")
@login_required
@require_onboarding
def chat():
    return render_if_exists("chat.html", fallback_endpoint="dashboard")


# -----------------------------------------------------------------------------
# Pep AI (Chat) API
# -----------------------------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

def _pep_ai_system_prompt(user_context: dict = None) -> str:
    """
    Generate intelligent system prompt with user context.
    Features 2-5: Context-aware, Protocol-aware, Progress tracking, Smart recommendations
    """
    
    base_prompt = """You are Pep AI, an intelligent research assistant for PeptideTracker.ai.

CRITICAL LEGAL BOUNDARIES - NEVER VIOLATE:
1. You are NOT a doctor, nurse, or licensed healthcare provider
2. You do NOT provide medical advice, diagnosis, or treatment
3. You do NOT recommend specific doses for individual users
4. You ALWAYS direct users to consult healthcare providers for medical decisions

WHAT YOU CAN DO (Educational + Intelligent):
✓ Explain how peptides work (mechanisms of action)
✓ Summarize published research studies
✓ Provide general dosing ranges from research literature
✓ Compare peptides based on research data
✓ Help users understand scientific concepts
✓ Calculate math (reconstitution, concentrations)
✓ Use user profile, protocols, and tracking data to filter relevant education
✓ Provide progress insights based on their tracking
✓ Suggest research-backed next steps (NOT medical prescriptions)

WHAT YOU CANNOT DO:
✗ Say "You should take X dose" or "I recommend X mcg for you"
✗ Say "This will cure/treat/fix your condition"
✗ Interpret symptoms medically or diagnose
✗ Tell them to start/stop protocols without provider consultation
✗ Make medical decisions"""

    # Add comprehensive user context if available
    if user_context:
        context_section = "\n\n═══ USER CONTEXT (for intelligent personalization) ═══\n"
        
        # FEATURE 2: Profile Context
        if user_context.get("profile"):
            profile = user_context["profile"]
            goals_display = ', '.join(profile.get('goals', []))
            context_section += f"""
📊 PROFILE:
• Age: {profile.get('age')} years | Weight: {profile.get('weight_lbs')} lbs | Height: {profile.get('height_inches')}" 
• Gender: {profile.get('gender')} | Experience: {profile.get('experience_level')}
• Primary Goals: {goals_display}"""
        
        # FEATURE 3: Active Protocols (if available)
        if user_context.get("active_protocols"):
            protocols = user_context["active_protocols"]
            context_section += f"\n\n💉 ACTIVE PROTOCOLS:"
            for p in protocols:
                context_section += f"\n• {p['name']}: {p['dose']} {p['frequency']}"
                if p.get('start_date'):
                    context_section += f" (Day {p['days_active']})"
        
        # FEATURE 4: Recent Progress (if available)
        if user_context.get("recent_injections"):
            inj_count = user_context["recent_injections"]["total"]
            compliance = user_context["recent_injections"]["compliance_rate"]
            context_section += f"\n\n📈 RECENT ACTIVITY (last 7 days):"
            context_section += f"\n• Injections logged: {inj_count}"
            context_section += f"\n• Compliance rate: {compliance}%"
            if compliance < 70:
                context_section += " (⚠️ below target)"
            elif compliance > 90:
                context_section += " (✓ excellent!)"
        
        # FEATURE 5: Smart Insights (if available)
        if user_context.get("insights"):
            insights = user_context["insights"]
            context_section += f"\n\n💡 INSIGHTS:"
            for insight in insights:
                context_section += f"\n• {insight}"
        
        context_section += "\n\n═══ HOW TO USE THIS CONTEXT ═══"
        context_section += """

PERSONALIZATION RULES:
1. **Goal Alignment**: Filter all education through their specific goals
   - If goals include "recovery" → emphasize tissue repair research
   - If goals include "fat_loss" → focus on metabolic peptides
   - If goals include "muscle_gain" → highlight anabolic effects

2. **Experience-Based Complexity**:
   - Beginner: Simpler explanations, more safety emphasis
   - Intermediate: Balanced detail, practical applications
   - Advanced: Technical depth, research citations

3. **Protocol Awareness** (CRITICAL):
   - Check for interactions with current protocols
   - Don't suggest peptides that conflict with active ones
   - Acknowledge what they're already doing: "I see you're using TB-500..."

4. **Progress Recognition**:
   - Acknowledge their compliance: "Your 95% adherence is excellent..."
   - Reference tracking: "Based on your X injections this month..."
   - Celebrate milestones: "You're on day 28 of your protocol..."

5. **Smart Suggestions**:
   - Cycle completion: "Your 6-week TB-500 cycle ends in 3 days. Research suggests..."
   - Stacking opportunities: "Given your recovery goals and current BPC-157, research shows TB-500 pairs well..."
   - Progression: "At intermediate level with 3 months experience, you might explore..."

RESPONSE FRAMEWORK:

When asked about dosing:
"Research shows [peptide] at [range]. Given your [profile factor], typical dosing in studies is [specific range]. Your healthcare provider can determine the appropriate dose for your situation."

When suggesting next steps:
"Based on your [goal] goals and [current protocol], research shows [peptide] is commonly explored next. Studies suggest [benefits]. Discuss with your provider whether this aligns with your health plan."

When acknowledging progress:
"I see you've logged [X injections] with [Y%] compliance - that's [assessment]! Research indicates [relevant finding for their stage]."

NEVER say: "You should do X"
ALWAYS say: "Research shows X. Discuss with your provider if Y fits your situation."
"""

        base_prompt += context_section

    # Add mandatory disclaimer
    base_prompt += """

═══ MANDATORY DISCLAIMER ═══
Include at end of ANY response about peptides/protocols/dosing:

---
⚠️ This is educational information from research literature, not medical advice. Always consult your healthcare provider before starting, stopping, or modifying any peptide protocol.

TONE: Intelligent, supportive, educational, safety-conscious. Like a knowledgeable research assistant who knows their data."""

    return base_prompt

def _call_openai_chat(message: str, user_context: dict = None) -> str:
    if not OPENAI_API_KEY:
        return "Pep AI is not configured yet (missing OPENAI_API_KEY). Please contact support."

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": _pep_ai_system_prompt(user_context)},
            {"role": "user", "content": message},
        ],
        "temperature": 0.4,
        "max_tokens": 1000,  # Increased for richer, context-aware responses
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 401:
            return "Pep AI configuration error: invalid OpenAI key."
        if resp.status_code >= 400:
            return f"Pep AI error ({resp.status_code}). Please try again."
        data = resp.json()
        return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "").strip() or "No response."
    except requests.exceptions.Timeout:
        return "Pep AI timed out. Please try again."
    except Exception as e:
        print(f"Pep AI exception: {e}")
        return "Pep AI encountered an error. Please try again."

def _build_comprehensive_user_context(user_id: int, db) -> dict:
    """
    Build comprehensive context about user for intelligent AI responses.
    Features 2-5: Profile, Protocols, Progress, Smart Insights
    """
    context = {}
    
    # FEATURE 2: User Profile
    try:
        profile = db.query(UserProfile).filter_by(user_id=user_id).first()
        if profile and profile.completed_at:
            context["profile"] = {
                "age": profile.age,
                "weight_lbs": profile.weight_lbs,
                "height_inches": profile.height_inches,
                "gender": profile.gender,
                "goals": json.loads(profile.goals) if profile.goals else [],
                "experience_level": profile.experience_level
            }
    except Exception as e:
        print(f"Error loading profile: {e}")
    
    # FEATURE 3: Active Protocols (placeholder - adapt if you have Protocol model)
    try:
        # If you have a Protocol/PeptideProtocol model, load it here
        # For now, this is a placeholder structure showing what to track
        # protocols = db.query(Protocol).filter_by(user_id=user_id, active=True).all()
        # if protocols:
        #     context["active_protocols"] = [
        #         {
        #             "name": p.peptide_name,
        #             "dose": p.dose_amount,
        #             "frequency": p.frequency,
        #             "start_date": p.start_date,
        #             "days_active": (datetime.utcnow() - p.start_date).days
        #         }
        #         for p in protocols
        #     ]
        pass
    except Exception as e:
        print(f"Error loading protocols: {e}")
    
    # FEATURE 4: Recent Progress & Compliance
    try:
        # If you have Injection tracking model
        # from datetime import timedelta
        # week_ago = datetime.utcnow() - timedelta(days=7)
        # recent_injections = db.query(Injection).filter(
        #     Injection.user_id == user_id,
        #     Injection.date >= week_ago
        # ).count()
        # 
        # if recent_injections > 0:
        #     # Calculate expected vs actual
        #     # expected = active_protocols * frequency * 7
        #     # compliance = (recent_injections / expected) * 100
        #     context["recent_injections"] = {
        #         "total": recent_injections,
        #         "compliance_rate": 85  # Calculate based on schedule
        #     }
        pass
    except Exception as e:
        print(f"Error loading injection history: {e}")
    
    # FEATURE 5: Smart Insights
    try:
        insights = []
        
        # Example insights based on data:
        # if context.get("recent_injections"):
        #     compliance = context["recent_injections"]["compliance_rate"]
        #     if compliance > 90:
        #         insights.append("Excellent compliance this week!")
        #     elif compliance < 70:
        #         insights.append("Compliance dropped - check reminders?")
        
        # if context.get("active_protocols"):
        #     for protocol in context["active_protocols"]:
        #         if protocol["days_active"] >= 40:
        #             insights.append(f"{protocol['name']} protocol nearing completion (typical 6-8 week cycle)")
        
        # if context.get("profile"):
        #     goals = context["profile"]["goals"]
        #     if "recovery" in goals and not context.get("active_protocols"):
        #         insights.append("No active recovery protocols - explore BPC-157 or TB-500 research")
        
        if insights:
            context["insights"] = insights
            
    except Exception as e:
        print(f"Error generating insights: {e}")
    
    return context

@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    """Pep AI chat endpoint used by templates/chat.html."""
    db = get_session(db_url)
    try:
        user = db.query(User).filter_by(id=session.get("user_id")).first()
        if not user:
            return jsonify({"error": "auth_required", "message": "Please log in."}), 401

        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"error": "bad_request", "message": "Message is required"}), 400

        # Free-tier metering: 10 free uses, then require upgrade.
        remaining = None
        if not tier_at_least(getattr(user, "tier", "free"), "tier1"):
            usage = db.query(PepAIUsage).filter_by(user_id=user.id).first()
            if not usage:
                usage = PepAIUsage(user_id=user.id, used=0)
                db.add(usage)
                db.commit()

            if usage.used >= FREE_PEP_AI_LIMIT:
                return jsonify({
                    "error": "limit_reached",
                    "message": "You’ve used your 10 free Pep AI questions.",
                    "remaining": 0
                }), 402

            # Count this request up-front (prevents accidental free retries).
            usage.used += 1
            db.commit()
            remaining = max(FREE_PEP_AI_LIMIT - usage.used, 0)

        # Build comprehensive user context (Features 2-5)
        user_context = _build_comprehensive_user_context(user.id, db)
        
        # Call AI with full context for intelligent responses
        reply = _call_openai_chat(message, user_context)

        resp = {"reply": reply}
        if remaining is not None:
            resp["remaining"] = remaining
        return jsonify(resp)
    except Exception as e:
        print(f"/api/chat error: {e}")
        return jsonify({"error": "server_error", "message": "Server error"}), 500
    finally:
        db.close()




@app.route("/upgrade")
def upgrade():
    # Placeholder upgrade page (Stripe integration can replace this later)
    return render_if_exists("upgrade.html", fallback_endpoint="dashboard")


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------


# ----------------------------
# Syringe Check (Dose + BAC verification) — idempotent registration
# ----------------------------
def _syringe_check():
    try:
        from database import PeptideDB  # type: ignore
        db = get_session(db_url)
        try:
            pdb = PeptideDB(db)
            protocols = getattr(pdb, "list_active_protocols", lambda: [])()
            vials = getattr(pdb, "list_active_vials", lambda: [])()
        finally:
            db.close()
    except Exception:
        app.logger.exception("Failed to load protocols/vials for syringe check")
        protocols, vials = [], []
    return render_if_exists("syringe_check.html", fallback_endpoint="dashboard", protocols=protocols, vials=vials, title="Syringe Check")


def _syringe_check_camera():
    try:
        from database import PeptideDB  # type: ignore
        db = get_session(db_url)
        try:
            pdb = PeptideDB(db)
            protocols = getattr(pdb, "list_active_protocols", lambda: [])()
            vials = getattr(pdb, "list_active_vials", lambda: [])()
        finally:
            db.close()
    except Exception:
        app.logger.exception("Failed to load protocols/vials for syringe camera check")
        protocols, vials = [], []
    return render_if_exists("syringe_check_camera.html", fallback_endpoint="syringe_check", protocols=protocols, vials=vials, title="Syringe Camera Check")


def _api_syringe_expected():
    protocol_id = (request.args.get("protocol_id") or "").strip()
    vial_id = (request.args.get("vial_id") or "").strip()
    dose_mcg_override = (request.args.get("dose_mcg") or "").strip()
    water_ml_override = (request.args.get("water_ml") or "").strip()

    protocol = None
    vial = None

    try:
        from database import PeptideDB  # type: ignore
        db = get_session(db_url)
        try:
            pdb = PeptideDB(db)

            if protocol_id:
                getp = getattr(pdb, "get_protocol", None) or getattr(pdb, "get_protocol_by_id", None)
                if callable(getp):
                    protocol = getp(int(protocol_id))
                else:
                    for p in getattr(pdb, "list_active_protocols", lambda: [])():
                        if getattr(p, "id", None) == int(protocol_id):
                            protocol = p
                            break

            if vial_id:
                getv = getattr(pdb, "get_vial", None) or getattr(pdb, "get_vial_by_id", None)
                if callable(getv):
                    vial = getv(int(vial_id))
                else:
                    for v in getattr(pdb, "list_active_vials", lambda: [])():
                        if getattr(v, "id", None) == int(vial_id):
                            vial = v
                            break
        finally:
            db.close()
    except Exception:
        app.logger.exception("Failed to load protocol/vial in syringe expected API")

    dose_mcg = None
    try:
        if dose_mcg_override:
            dose_mcg = float(dose_mcg_override)
    except Exception:
        dose_mcg = None

    if dose_mcg is None and protocol is not None:
        try:
            dose_mcg = float(getattr(protocol, "dose_mcg", None))
        except Exception:
            dose_mcg = None

    mg_amount = None
    try:
        if vial is not None:
            mg_amount = float(getattr(vial, "mg_amount", None))
    except Exception:
        mg_amount = None

    water_ml = None
    try:
        if water_ml_override:
            water_ml = float(water_ml_override)
        elif vial is not None:
            water_ml = float(getattr(vial, "bacteriostatic_water_ml", None))
    except Exception:
        water_ml = None

    mg_per_ml = None
    mcg_per_ml = None
    expected_volume_ml = None
    expected_units_u100 = None

    if mg_amount and water_ml and water_ml > 0:
        mg_per_ml = mg_amount / water_ml
        mcg_per_ml = mg_per_ml * 1000.0

    if dose_mcg and mcg_per_ml and mcg_per_ml > 0:
        expected_volume_ml = dose_mcg / mcg_per_ml
        expected_units_u100 = expected_volume_ml * 100.0

    return jsonify(
        {
            "protocol_id": int(protocol_id) if protocol_id.isdigit() else None,
            "vial_id": int(vial_id) if vial_id.isdigit() else None,
            "dose_mcg": dose_mcg,
            "vial_mg_amount": mg_amount,
            "water_ml": water_ml,
            "mg_per_ml": mg_per_ml,
            "mcg_per_ml": mcg_per_ml,
            "expected_volume_ml": expected_volume_ml,
            "expected_units_u100": expected_units_u100,
        }
    )


# Register routes only if they don't already exist
if "login_required" in globals():
    register_route("/syringe-check", "syringe_check", login_required(_syringe_check))
    register_route("/syringe-check/camera", "syringe_check_camera", login_required(_syringe_check_camera))
    register_route("/api/syringe-check/expected", "api_syringe_check_expected", login_required(_api_syringe_expected))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)


FREE_TRIAL_LIMIT = 10  # free tier Pep AI messages


# -----------------------------------------------------------------------------
# Confidence Score API (data-alignment + verification confidence)
# -----------------------------------------------------------------------------
@app.route("/api/injection-confidence", methods=["POST"])
@login_required
def api_injection_confidence():
    """
    POST JSON payload (see confidence.compute_injection_confidence docstring).
    Returns: {score, band, reasons}
    """
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}

    result = compute_injection_confidence(payload)
    # Do NOT return debug by default in production; keep for now for tuning.
    include_debug = bool(request.args.get("debug"))
    if not include_debug and "debug" in result:
        result.pop("debug", None)
    return jsonify(result)
