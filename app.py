"""
Peptide Tracker Web Application (Template-contract safe)

UPDATED: 
- Added USDA Nutrition API integration
- Added password reset functionality
- Fixed calculator route (now peptide-calculator)
"""

from __future__ import annotations

import os
import json
import requests
import base64

import secrets
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
try:
    from PIL import Image
except ImportError:
    Image = None
import io
from typing import Any, Dict, List, Tuple

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, render_template_string, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound

from sqlalchemy import Column, Integer, String, DateTime, Float, text
from config import Config
from models import get_session, create_engine, Base as ModelBase

# Import nutrition API
from nutrition_api import register_nutrition_routes

# -----------------------------------------------------------------------------
# Flask app
# -----------------------------------------------------------------------------
app = Flask(

# -----------------------------------------------------------------------------
# Food scanning configuration (used by /scan-food and /api/* endpoints)
# -----------------------------------------------------------------------------
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

USDA_API_KEY = os.environ.get("USDA_API_KEY")
CALORIENINJAS_API_KEY = os.environ.get("CALORIENINJAS_API_KEY")

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS



# -----------------------------------------------------------------------------
# USDA FoodData Central API helper
# -----------------------------------------------------------------------------
def search_usda_food(query: str, page_size: int = 5) -> dict:
    if not USDA_API_KEY:
        return {"error": "USDA API key not configured"}
    try:
        url = "https://api.nal.usda.gov/fdc/v1/foods/search"
        params = {
            "api_key": USDA_API_KEY,
            "query": query,
            "pageSize": page_size,
            "dataType": ["Foundation", "SR Legacy"],
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return {"error": f"USDA API error: {resp.status_code}"}
        data = resp.json()
        foods = data.get("foods", []) or []
        results = []
        for food in foods:
            nutrients = {n.get("nutrientName"): n.get("value", 0) for n in food.get("foodNutrients", [])}
            results.append({
                "description": food.get("description", "Unknown"),
                "fdcId": food.get("fdcId"),
                "calories": nutrients.get("Energy", 0),
                "protein": nutrients.get("Protein", 0),
                "carbs": nutrients.get("Carbohydrate, by difference", 0),
                "fat": nutrients.get("Total lipid (fat)", 0),
                "fiber": nutrients.get("Fiber, total dietary", 0),
                "sugar": nutrients.get("Sugars, total including NLEA", 0),
                "serving_size": "100g",
                "data_type": food.get("dataType", "Unknown"),
            })
        return {"foods": results, "total": data.get("totalHits", 0)}
    except requests.exceptions.Timeout:
        return {"error": "USDA API timeout"}
    except Exception as e:
        return {"error": f"USDA API error: {str(e)}"}

def search_calorieninjas_food(query: str) -> dict:
    if not CALORIENINJAS_API_KEY:
        return {"error": "CalorieNinjas API key not configured"}
    try:
        url = "https://api.calorieninjas.com/v1/nutrition"
        params = {"query": query}
        headers = {"X-Api-Key": CALORIENINJAS_API_KEY}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"error": f"CalorieNinjas API error: {resp.status_code}"}
        data = resp.json()
        items = data.get("items", []) or []
        results = []
        for item in items:
            results.append({
                "description": item.get("name", ""),
                "calories": item.get("calories", 0),
                "protein": item.get("protein_g", 0),
                "carbs": item.get("carbohydrates_total_g", 0),
                "fat": item.get("fat_total_g", 0),
                "fiber": item.get("fiber_g", 0),
                "sugar": item.get("sugar_g", 0),
                "serving_size": f"{item.get('serving_size_g', 100)}g",
            })
        return {"foods": results, "total": len(results)}
    except Exception as e:
        return {"error": str(e)}

# -----------------------------------------------------------------------------
# OpenAI Vision helper for food detection
# -----------------------------------------------------------------------------
def _openai_identify_food_from_image(image_b64: str) -> dict:
    """Return {name, confidence (0-1), alternatives[], notes}."""
    if not OPENAI_API_KEY:
        return {"error": "Missing OPENAI_API_KEY"}

    # Use a vision-capable model; reuse OPENAI_MODEL default in your app (gpt-4o-mini)
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    # Data URL format
    data_url = f"data:image/jpeg;base64,{image_b64}"

    sys = (
        "You are a food recognition assistant. "
        "Identify the primary food item in the image. "
        "Return STRICT JSON only with keys: name (string), confidence (number 0-1), alternatives (array of strings), notes (string). "
        "If multiple foods, choose the main one and list others in alternatives. "
        "Be concise."
    )
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": [
                {"type": "text", "text": "What food is in this image? Return JSON only."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        "temperature": 0.2,
        "max_tokens": 250,
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        if r.status_code != 200:
            return {"error": f"OpenAI error: {r.status_code}", "details": r.text[:300]}
        out = r.json()
        content = out["choices"][0]["message"]["content"].strip()
        # Parse JSON safely; sometimes wrapped in ```json
        content = re.sub(r"^```json\s*|```$", "", content).strip()
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}

__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

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
    user_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    description = Column(String(500), nullable=False)
    
    # Nutrition totals
    total_calories = Column(Float, default=0)
    total_protein_g = Column(Float, default=0)
    total_fat_g = Column(Float, default=0)
    total_carbs_g = Column(Float, default=0)
    
    # Raw API response
    raw_data = Column(String(5000))

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

ModelBase.metadata.create_all(engine)
ensure_users_tier_column(engine)

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
        
        # Check if user has completed profile.
        # Since profile setup is now integrated into the dashboard, we allow the dashboard
        # to load even if the profile is incomplete, and we redirect other protected pages
        # back to the dashboard until the profile is completed.
        if f.__name__ not in ("profile_setup", "dashboard", "chat", "api_chat"):
            db = get_session(db_url)
            try:
                profile = db.query(UserProfile).filter_by(user_id=session["user_id"]).first()
                if not profile or not profile.completed_at:
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
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        u = get_current_user()
        if not u:
            return redirect(url_for("login"))
        # Step 1: profile
        if not is_profile_complete(u.id) and request.endpoint not in {"profile_setup", "logout", "onboarding_step_1", "onboarding_step_2", "medical_disclaimer"}:
            return redirect(url_for("onboarding_step_1"))
        # Step 2: disclaimer acknowledgement
        if is_profile_complete(u.id) and not has_accepted_disclaimer(u.id) and request.endpoint not in {"onboarding_step_2", "logout", "medical_disclaimer"}:
            return redirect(url_for("onboarding_step_2"))
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




# -----------------------------------------------------------------------------
# NEW: Camera Food Scanner with Instant Nutrition
# -----------------------------------------------------------------------------
@app.route("/scan-food", methods=["GET"])
@login_required
def scan_food():
    return render_template("scan_food.html", title="Scan Food")

@app.route("/api/scan-food-image", methods=["POST"])
@login_required
def api_scan_food_image():
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400

    file = request.files["image"]
    if not file or file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Use JPG, PNG, or WEBP"}), 400

    try:
        image_data = file.read()
        if len(image_data) > MAX_IMAGE_SIZE:
            return jsonify({"error": "Image too large (max 10MB)"}), 400

        # Basic image validation if Pillow is available
        if Image is not None:
            try:
                img = Image.open(io.BytesIO(image_data))
                img.verify()
            except Exception:
                return jsonify({"error": "Invalid image file"}), 400

        image_b64 = base64.b64encode(image_data).decode("utf-8")

        food_detection = _openai_identify_food_from_image(image_b64)
        if "error" in food_detection:
            return jsonify({"error": "Food detection failed", "details": food_detection.get("error")}), 500

        detected_food_name = (food_detection.get("name") or "").strip()
        confidence = float(food_detection.get("confidence") or 0)
        alternatives = food_detection.get("alternatives") or []
        notes = food_detection.get("notes") or ""

        if not detected_food_name:
            return jsonify({"error": "Could not identify food in image"}), 400

        usda_results = search_usda_food(detected_food_name, page_size=3)
        ninja_results = search_calorieninjas_food(detected_food_name)

        all_foods = []
        if "foods" in usda_results:
            for food in usda_results["foods"]:
                food["source"] = "USDA"
                all_foods.append(food)
        if "foods" in ninja_results:
            for food in ninja_results["foods"]:
                food["source"] = "CalorieNinjas"
                all_foods.append(food)

        if not all_foods:
            return jsonify({
                "error": "No nutrition data found",
                "detected_food": detected_food_name,
                "confidence": confidence,
                "alternatives": alternatives,
            }), 404

        return jsonify({
            "success": True,
            "detected_food": detected_food_name,
            "confidence": confidence,
            "alternatives": alternatives,
            "notes": notes,
            "foods": all_foods[:5],
            "total_results": len(all_foods),
        })
    except Exception as e:
        return jsonify({"error": "Server error processing image", "details": str(e)}), 500

@app.route("/api/nutrition-search", methods=["GET"])
@login_required
def api_nutrition_search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "No search query provided"}), 400

    usda_results = search_usda_food(query, page_size=10)
    ninja_results = search_calorieninjas_food(query)

    all_foods = []
    if "foods" in usda_results:
        for food in usda_results["foods"]:
            food["source"] = "USDA"
            all_foods.append(food)
    if "foods" in ninja_results:
        for food in ninja_results["foods"]:
            food["source"] = "CalorieNinjas"
            all_foods.append(food)

    return jsonify({"success": True, "query": query, "foods": all_foods, "total": len(all_foods)})



@app.route("/scan-nutrition", methods=["GET"])
@login_required
def scan_nutrition():
    # Alias route used by navbar. Reuse the working Scan Food experience.
    if request.args.get("autocam") == "1":
        return redirect(url_for("scan_food") + "?autocam=1")
    return redirect(url_for("scan_food"))


@app.route("/scan-peptides", methods=["GET"])
@login_required
def scan_peptides():
    # Avoid Jinja rendering here to prevent 500s caused by template parsing issues.
    peptides = _load_peptides_list()
    peptide_names = [p.get("name", "") for p in peptides if p.get("name")]
    peptide_names_json = json.dumps(peptide_names)

    html = f"""<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Scan Peptides</title>
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; margin:16px; background:#f7f7fb;}}
    .card{{background:#fff;border:1px solid #e6e6ef;border-radius:14px;padding:14px;box-shadow:0 1px 8px rgba(0,0,0,.04); max-width:720px; margin:0 auto;}}
    h1{{font-size:20px;margin:0 0 6px;}}
    .muted{{color:#666;font-size:13px;line-height:1.4}}
    input[type=file]{{width:100%;}}
    .btn{{display:inline-flex;align-items:center;justify-content:center; gap:8px; padding:10px 12px; border-radius:12px; border:1px solid #d9d9e6; background:#111827; color:#fff; font-weight:700; cursor:pointer;}}
    .btn:disabled{{opacity:.55;cursor:not-allowed;}}
    .btn.secondary{{background:#fff;color:#111827;}}
    .row{{display:flex;gap:10px;flex-wrap:wrap;}}
    .pill{{display:inline-flex;align-items:center;gap:6px;background:#eef2ff;border:1px solid #dbe3ff;padding:6px 10px;border-radius:999px;font-size:12px;color:#233;}}
    .out{{white-space:pre-wrap;background:#0b1020;color:#d7e2ff;border-radius:12px;padding:10px;font-size:12px;min-height:64px;}}
    .label{{font-size:12px;color:#444;margin:10px 0 4px;}}
  </style>
</head>
<body>
  <div class="card">
    <h1>Scan Peptides</h1>
    <div class="muted">Take a photo of the kit/box label. We’ll OCR it and suggest the closest peptide name.</div>

    <div class="label">Upload a photo</div>
    <input id="peptidePhoto" type="file" accept="image/*" capture="environment" />

    <div class="mt-3">
      <div class="row">
        <button class="btn secondary" type="button" id="openCameraBtn">📷 Use Camera</button>
        <button class="btn secondary" type="button" id="captureFrameBtn" style="display:none;">⏺ Capture Photo</button>
        <button class="btn secondary" type="button" id="stopCameraBtn" style="display:none;">✖ Stop</button>
      </div>
      <div id="cameraWrap" style="display:none;margin-top:10px;">
        <video id="cameraStream" playsinline autoplay style="width:100%;border-radius:12px;border:1px solid #e6e6ef;"></video>
        <canvas id="cameraCanvas" style="display:none;"></canvas>
      </div>
    </div>

    <div class="label">OCR Result</div>
    <div class="out" id="ocrOut">Waiting…</div>

    <div class="label">Best Match</div>
    <div class="pill" id="matchPill">—</div>

    <div class="label">Actions</div>
    <div class="row">
      <button class="btn" type="button" id="copyBtn" disabled>Copy Result</button>
      <button class="btn secondary" type="button" onclick="window.location.href='/vials'">Go to Vials</button>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>
  <script>
    const peptideNames = {peptide_names_json};

    const pepPhoto = document.getElementById("peptidePhoto");
    const ocrOut = document.getElementById("ocrOut");
    const matchPill = document.getElementById("matchPill");
    const copyBtn = document.getElementById("copyBtn");

    function normalize(s) {{
      return (s||"").toUpperCase().replace(/[^A-Z0-9\-\s]/g," ").replace(/\s+/g," ").trim();
    }}

    function scoreMatch(text, name) {{
      const t = normalize(text);
      const n = normalize(name);
      if (!t || !n) return 0;
      if (t.includes(n)) return 100;
      const tParts = new Set(t.split(" "));
      const nParts = new Set(n.split(" "));
      let hit = 0;
      nParts.forEach(p => {{ if (tParts.has(p)) hit++; }});
      return Math.round((hit / Math.max(1, nParts.size)) * 90);
    }}

    function bestMatch(text) {{
      let best = {{name:"—", score:0}};
      for (const n of peptideNames) {{
        const sc = scoreMatch(text, n);
        if (sc > best.score) best = {{name:n, score:sc}};
      }}
      return best;
    }}

    async function runOCR(file) {{
      ocrOut.textContent = "Reading image…";
      matchPill.textContent = "—";
      copyBtn.disabled = true;

      try {{
        const {{ data: {{ text }} }} = await Tesseract.recognize(file, "eng");
        const cleaned = (text || "").trim();
        ocrOut.textContent = cleaned || "(no text found)";
        const bm = bestMatch(cleaned);
        matchPill.textContent = bm.name === "—" ? "No match" : `${{bm.name}} (score ${{bm.score}})`;
        copyBtn.disabled = !cleaned;
        copyBtn.onclick = () => navigator.clipboard.writeText(cleaned);
      }} catch (e) {{
        console.error(e);
        ocrOut.textContent = "OCR failed. Try a clearer photo or better lighting.";
      }}
    }}

    pepPhoto.addEventListener("change", (e) => {{
      const f = e.target.files && e.target.files[0];
      if (f) runOCR(f);
    }});

    let cameraStream = null;

    async function startCamera() {{
      const wrap = document.getElementById('cameraWrap');
      const video = document.getElementById('cameraStream');
      const openBtn = document.getElementById('openCameraBtn');
      const capBtn = document.getElementById('captureFrameBtn');
      const stopBtn = document.getElementById('stopCameraBtn');

      try {{
        cameraStream = await navigator.mediaDevices.getUserMedia({{
          video: {{ facingMode: {{ ideal: "environment" }} }},
          audio: false
        }});
        video.srcObject = cameraStream;
        wrap.style.display = 'block';
        capBtn.style.display = 'inline-flex';
        stopBtn.style.display = 'inline-flex';
        openBtn.style.display = 'none';
      }} catch (e) {{
        console.error(e);
        alert("Could not access camera. You can still use the Upload Photo option.");
      }}
    }}

    function stopCamera() {{
      const wrap = document.getElementById('cameraWrap');
      const openBtn = document.getElementById('openCameraBtn');
      const capBtn = document.getElementById('captureFrameBtn');
      const stopBtn = document.getElementById('stopCameraBtn');
      const video = document.getElementById('cameraStream');

      if (cameraStream) {{
        cameraStream.getTracks().forEach(t => t.stop());
        cameraStream = null;
      }}
      video.srcObject = null;
      wrap.style.display = 'none';
      capBtn.style.display = 'none';
      stopBtn.style.display = 'none';
      openBtn.style.display = 'inline-flex';
    }}

    function capturePhotoToFileInput() {{
      const video = document.getElementById('cameraStream');
      const canvas = document.getElementById('cameraCanvas');
      const input = document.getElementById('peptidePhoto');

      const w = video.videoWidth || 1280;
      const h = video.videoHeight || 720;
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, w, h);

      canvas.toBlob(blob => {{
        if (!blob) return;
        const file = new File([blob], "camera.jpg", {{ type: "image/jpeg" }});
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;

        const evt = new Event('change', {{ bubbles: true }});
        input.dispatchEvent(evt);

        stopCamera();
      }}, "image/jpeg", 0.92);
    }}

    document.getElementById('openCameraBtn')?.addEventListener('click', startCamera);
    document.getElementById('stopCameraBtn')?.addEventListener('click', stopCamera);
    document.getElementById('captureFrameBtn')?.addEventListener('click', capturePhotoToFileInput);

    window.addEventListener('DOMContentLoaded', () => {{
      const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || window.matchMedia('(max-width: 768px)').matches;
      if (!isMobile) return;

      const params = new URLSearchParams(window.location.search);
      const wantsAuto = params.get('autocam') === '1';
      if (!wantsAuto) return;

      const key = 'autocam_once:/scan-peptides';
      if (sessionStorage.getItem(key) === '1') return;

      sessionStorage.setItem(key, '1');
      try {{
        params.delete('autocam');
        const newUrl = window.location.pathname + (params.toString() ? ('?' + params.toString()) : '') + window.location.hash;
        history.replaceState(null, '', newUrl);
      }} catch (e) {{}}

      setTimeout(() => {{ startCamera(); }}, 350);
    }});
  </script>
</body>
</html>"""

    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store"
    return resp


        pass


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
    return render_if_exists(
        "dashboard.html",
        fallback_endpoint="index",
        stats=stats,
        protocols=protocols,
        recent_injections=recent_injections,
        profile=profile,
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

    # If profile isn't complete yet, force step 1 first
    if not is_profile_complete(u.id):
        return redirect(url_for("onboarding_step_1"))

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
            food_log = FoodLog(                description=description,
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

def _pep_ai_system_prompt() -> str:
    return (
        "You are Pep AI inside PeptideTracker.ai. "
        "You provide educational, research-oriented information only. "
        "No medical advice, diagnosis, treatment recommendations, or dosing instructions. "
        "If the user asks for dosing, prescriptions, or medical decisions, refuse and suggest they consult a licensed clinician. "
        "You can help with math (e.g., reconstitution concentration calculations) and summarize study abstracts at a high level. "
        "Always encourage safety, verification, and professional guidance."
    )

def _call_openai_chat(message: str) -> str:
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
            {"role": "system", "content": _pep_ai_system_prompt()},
            {"role": "user", "content": message},
        ],
        "temperature": 0.4,
        "max_tokens": 500,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=25)
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

        reply = _call_openai_chat(message)

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
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)


FREE_TRIAL_LIMIT = 10  # free tier Pep AI messages
