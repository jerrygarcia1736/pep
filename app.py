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
import secrets
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Tuple

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
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
    tier = Column(String(20), nullable=False, default="free")  # free | tier1 | tier2 | admin
    created_at = Column(DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

# Food log model for nutrition tracking
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

# -----------------------------------------------------------------------------
# DB init + migration
# -----------------------------------------------------------------------------
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
        return {"current_user": AnonymousUser(), "has_endpoint": has_endpoint, "tier_at_least": tier_at_least}

    user.is_authenticated = True
    if not getattr(user, "tier", None):
        user.tier = "free"

    return {"current_user": user, "has_endpoint": has_endpoint, "tier_at_least": tier_at_least}

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
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_if_exists("index.html", fallback_endpoint="register")

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
def dashboard():
    stats, protocols, recent_injections = _compute_dashboard_context()
    return render_if_exists(
        "dashboard.html",
        fallback_endpoint="index",
        stats=stats,
        protocols=protocols,
        recent_injections=recent_injections,
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
def pep_ai():
    return redirect(url_for("chat"))


@app.route("/calculator")
@login_required
def calculator():
    """Legacy route - redirects to peptide-calculator"""
    return redirect(url_for("peptide_calculator"))

@app.route("/peptide-calculator", methods=["GET", "POST"])
@login_required
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
def protocols():
    return render_if_exists("protocols.html", fallback_endpoint="dashboard")

@app.route("/vials")
@login_required
def vials():
    return render_if_exists("vials.html", fallback_endpoint="dashboard")

@app.route("/history")
@login_required
def history():
    return render_if_exists("history.html", fallback_endpoint="dashboard")

@app.route("/coaching")
@login_required
def coaching():
    return render_if_exists("coaching.html", fallback_endpoint="dashboard")

@app.route("/chat")
@login_required
def chat():
    return render_if_exists("chat.html", fallback_endpoint="dashboard")

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
