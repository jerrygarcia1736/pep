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
    agreement_accepted_at = Column(DateTime, nullable=True)  # NULL = not accepted yet

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

def ensure_users_agreement_column(engine) -> None:
    """Add users.agreement_accepted_at on legacy DBs (safe no-op if already present)."""
    try:
        dialect = (engine.dialect.name or "").lower()
        if dialect.startswith("postgres"):
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS agreement_accepted_at TIMESTAMP NULL;")
                )
        elif dialect.startswith("sqlite"):
            with engine.begin() as conn:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users);")).fetchall()]
                if "agreement_accepted_at" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN agreement_accepted_at TIMESTAMP NULL;"))
    except Exception as e:
        print(f"Warning: could not ensure users.agreement_accepted_at column: {e}")

ModelBase.metadata.create_all(engine)
ensure_users_tier_column(engine)
ensure_users_agreement_column(engine)

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
        
        # Check if user has accepted agreement (only if column exists)
        db = get_session(db_url)
        try:
            user = db.query(User).filter_by(id=session["user_id"]).first()
            # Try to check agreement, but don't fail if column doesn't exist yet
            try:
                if user and hasattr(user, 'agreement_accepted_at') and not user.agreement_accepted_at:
                    return redirect(url_for("user_agreement"))
            except:
                pass  # Column doesn't exist yet, skip check
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
# Legal Pages and User Agreement
# -----------------------------------------------------------------------------
@app.route("/terms-of-service")
def terms_of_service():
    """Terms of Service page"""
    return render_if_exists("terms_of_service.html", fallback_endpoint="dashboard")


@app.route("/medical-disclaimer")
def medical_disclaimer():
    """Medical Disclaimer page"""
    return render_if_exists("medical_disclaimer.html", fallback_endpoint="dashboard")


@app.route("/user-agreement")
@login_required
def user_agreement():
    """User agreement that must be accepted before using the app"""
    # Don't check for agreement in this route (would cause infinite loop)
    return render_template("user_agreement.html")


@app.route("/accept-agreement", methods=["POST"])
def accept_agreement():
    """Process user agreement acceptance"""
    if "user_id" not in session:
        flash("Please log in.", "warning")
        return redirect(url_for("login"))
    
    db = get_session(db_url)
    try:
        user = db.query(User).filter_by(id=session["user_id"]).first()
        if user:
            # Mark agreement as accepted with timestamp
            user.agreement_accepted_at = datetime.utcnow()
            db.commit()
            flash("Agreement accepted. Welcome to PeptideTracker.ai!", "success")
            return redirect(url_for("dashboard"))
    finally:
        db.close()
    
    flash("Error processing agreement.", "error")
    return redirect(url_for("user_agreement"))

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
    if request.method == "POST":
        flash("add_vial is not wired yet (stub).", "info")
        return redirect(url_for("dashboard"))
    return render_if_exists("add_vial.html", fallback_endpoint="dashboard")

@app.route("/add-protocol", methods=["GET", "POST"])
@login_required
def add_protocol():
    if request.method == "POST":
        flash("add_protocol is not wired yet (stub).", "info")
        return redirect(url_for("dashboard"))
    return render_if_exists("add_protocol.html", fallback_endpoint="dashboard")

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
                        food_log = FoodLog(
                            user_id=session["user_id"],
                            description=food_description,
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
            food_log = FoodLog(
                user_id=session["user_id"],
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
def peptides():
    return render_if_exists("peptides.html", fallback_endpoint="dashboard")

@app.route("/calculator")
@login_required
def calculator():
    """Legacy route - redirects to peptide-calculator"""
    return redirect(url_for("peptide_calculator"))

@app.route("/peptide-calculator")
@login_required
def peptide_calculator():
    """Peptide Calculator - NEW route name"""
    return render_if_exists("calculator.html", fallback_endpoint="dashboard")

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
# Pep AI Chat API with Safe System Prompt
# -----------------------------------------------------------------------------
@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    """Chat with Pep AI using legally safe system prompt"""
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        
        if not user_message:
            return jsonify({"error": "Message required"}), 400
        
        # Get basic user context (optional - use for filtering education)
        db = get_session(db_url)
        user_context = {}
        try:
            user = db.query(User).filter_by(id=session["user_id"]).first()
            if user:
                user_context = {
                    "username": user.username,
                    "tier": user.tier,
                    "account_age_days": (datetime.utcnow() - user.created_at).days
                }
        finally:
            db.close()
        
        # SAFE SYSTEM PROMPT - Legally Protected
        system_prompt = f"""You are Pep AI, an educational research assistant for PeptideTracker.ai.

CRITICAL LEGAL BOUNDARIES - NEVER VIOLATE:
1. You are NOT a doctor, nurse, or licensed healthcare provider
2. You do NOT provide medical advice, diagnosis, or treatment
3. You do NOT recommend specific doses for individual users
4. You do NOT interpret symptoms or diagnose conditions
5. You do NOT prescribe or suggest treatment plans
6. You ALWAYS direct users to consult healthcare providers for medical decisions

WHAT YOU CAN DO (Educational):
✓ Explain how peptides work (mechanisms of action)
✓ Summarize published research studies
✓ Provide general dosing ranges from research literature
✓ Compare peptides based on research data
✓ Help users understand scientific concepts
✓ Assist with tracking and organizing their data
✓ Calculate math (e.g., concentration, reconstitution)
✓ Answer questions about peptide properties

WHAT YOU CANNOT DO:
✗ Say "You should take X dose" or "I recommend X mcg for you"
✗ Say "This will cure/treat/fix your condition"
✗ Interpret their symptoms or side effects medically
✗ Tell them to start, stop, or change their protocol
✗ Make decisions for them
✗ Replace their doctor

USER CONTEXT (for reference only):
{json.dumps(user_context, indent=2)}

RESPONSE FRAMEWORK:

When asked about dosages:
❌ BAD: "Based on your weight and goals, you should take 250mcg"
✅ GOOD: "Research shows BPC-157 is typically studied at 250-500mcg twice daily. These are general ranges from literature. Your healthcare provider can determine the appropriate dose for your specific situation, considering factors like your medical history, current health status, and individual needs."

When asked about starting a peptide:
❌ BAD: "Yes, you should start BPC-157 for your injury"
✅ GOOD: "BPC-157 has been studied for tissue repair and recovery. Research suggests it may support healing processes. However, before starting any peptide, you'll want to discuss with your healthcare provider to ensure it's appropriate for your specific situation and to get proper medical oversight."

When asked about side effects or symptoms:
❌ BAD: "That sounds like X condition, try Y"
✅ GOOD: "These symptoms should be evaluated by your healthcare provider who can properly assess your situation. They'll be able to determine if this is related to the peptide or something else requiring attention."

MANDATORY DISCLAIMER:
Include this at the end of EVERY response that discusses peptides, dosing, or protocols:

---
⚠️ This is educational information from research literature, not medical advice. Always consult your healthcare provider before starting, stopping, or modifying any peptide protocol.

TONE:
- Friendly and helpful
- Educational and informative
- Safety-conscious
- Encouraging users to work with medical professionals
- Never dismissive or directive

Remember: Your purpose is to EDUCATE and INFORM, not to PRESCRIBE or DIAGNOSE."""
        
        # Call Claude API (no API key needed per your setup)
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_message}
                ]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            ai_response = response.json()
            return jsonify({
                "success": True,
                "response": ai_response["content"][0]["text"]
            })
        else:
            print(f"Claude API error: {response.status_code} - {response.text}")
            return jsonify({
                "success": False,
                "error": "Failed to get response from AI"
            }), 500
        
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({
            "success": False,
            "error": "Chat service temporarily unavailable"
        }), 500

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host="0.0.0.0", port=port, debug=debug)
