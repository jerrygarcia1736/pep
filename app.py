"""
Peptide Tracker Web Application
Flask web interface with user authentication + age/goals recommendations + peptide compare
"""

from __future__ import annotations

import os
import requests
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy import Column, Integer, String, DateTime, text

# Your project modules
from config import Config
from models import get_session, create_engine, Base as ModelBase, Peptide
from database import PeptideDB
from calculator import PeptideCalculator

# OpenAI (modern SDK)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# -------------------------
# DB safety migration helper
# -------------------------
def ensure_peptides_image_filename_column(engine):
    """Ensure peptides.image_filename exists (Postgres/SQLite). Safe to call on every startup."""
    try:
        dialect = (engine.dialect.name or "").lower()
        if dialect.startswith("postgres"):
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE peptides ADD COLUMN IF NOT EXISTS image_filename VARCHAR(255);"))
        elif dialect.startswith("sqlite"):
            with engine.begin() as conn:
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(peptides);")).fetchall()]
                if "image_filename" not in cols:
                    conn.execute(text("ALTER TABLE peptides ADD COLUMN image_filename VARCHAR(255);"))
        else:
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE peptides ADD COLUMN image_filename VARCHAR(255);"))
                except Exception:
                    pass
    except Exception as e:
        print(f"Warning: could not ensure image_filename column: {e}")


# -------------------------
# User model (local)
# -------------------------
class User(ModelBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username}>"


# -------------------------
# Flask app init
# -------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")


# -------------------------
# DB init
# -------------------------
db_url = Config.DATABASE_URL
print(f"Using database: {db_url[:20]}...")

engine = create_engine(db_url)
ensure_peptides_image_filename_column(engine)
ModelBase.metadata.create_all(engine)


def init_database():
    """Seed peptides on first run (if empty)."""
    try:
        from seed_data import seed_common_peptides
    except Exception as e:
        print(f"Warning: seed_data import failed: {e}")
        return

    db_session = get_session(db_url)
    db = PeptideDB(db_session)

    try:
        peptide_count = len(db.list_peptides())
        if peptide_count == 0:
            print("Database is empty, seeding with common peptides...")
            seed_common_peptides(db_session)
            print(f"Seeded {len(db.list_peptides())} peptides")
        else:
            print(f"Database already has {peptide_count} peptides")
    finally:
        db_session.close()


try:
    init_database()
except Exception as e:
    print(f"Warning: Could not initialize database: {e}")


# -------------------------
# Auth helpers
# -------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def get_current_user():
    if "user_id" in session:
        db_session = get_session(db_url)
        try:
            return db_session.query(User).filter_by(id=session["user_id"]).first()
        finally:
            db_session.close()
    return None


# ==================== AUTH ROUTES ====================
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for("register"))

        db_session = get_session(db_url)
        try:
            existing_user = db_session.query(User).filter(
                (User.username == username) | (User.email == email)
            ).first()
            if existing_user:
                flash("Username or email already exists.", "danger")
                return redirect(url_for("register"))

            user = User(username=username, email=email)
            user.set_password(password)
            db_session.add(user)
            db_session.commit()

            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        finally:
            db_session.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        db_session = get_session(db_url)
        try:
            user = db_session.query(User).filter_by(username=username).first()
            if user and user.check_password(password):
                session["user_id"] = user.id
                session["username"] = user.username
                flash(f"Welcome back, {user.username}!", "success")
                return redirect(url_for("dashboard"))
        finally:
            db_session.close()

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ==================== MAIN ROUTES ====================
@app.route("/dashboard")
@login_required
def dashboard():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        active_protocols = db.list_active_protocols()
        recent_injections = db.get_recent_injections(days=7)
        active_vials = db.list_active_vials()

        stats = {
            "active_protocols": len(active_protocols),
            "active_vials": len(active_vials),
            "injections_this_week": len(recent_injections),
            "total_peptides": len(db.list_peptides()),
        }
        return render_template(
            "dashboard.html",
            stats=stats,
            protocols=active_protocols,
            recent_injections=recent_injections[:5],
        )
    finally:
        db_session.close()


@app.route("/peptides")
@login_required
def peptides():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        all_peptides = db.list_peptides()
        return render_template("peptides.html", peptides=all_peptides)
    finally:
        db_session.close()


@app.route("/peptides/<int:peptide_id>")
@login_required
def peptide_detail(peptide_id):
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        peptide = db.get_peptide(peptide_id)
        if not peptide:
            flash("Peptide not found.", "danger")
            return redirect(url_for("peptides"))

        research = db.get_peptide_research(peptide_id)
        return render_template("peptide_detail.html", peptide=peptide, research=research)
    finally:
        db_session.close()


@app.route("/calculator", methods=["GET", "POST"])
@login_required
def calculator():
    result = None
    if request.method == "POST":
        try:
            peptide_name = request.form.get("peptide_name")
            mg_amount = float(request.form.get("mg_amount"))
            ml_water = float(request.form.get("ml_water"))
            dose_mcg = float(request.form.get("dose_mcg"))
            doses_per_day = int(request.form.get("doses_per_day"))

            result = PeptideCalculator.full_reconstitution_report(
                peptide_name, mg_amount, ml_water, dose_mcg, doses_per_day
            )
        except (ValueError, TypeError) as e:
            flash(f"Invalid input: {e}", "danger")

    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        peptide_list = db.list_peptides()
        return render_template("calculator.html", result=result, peptides=peptide_list)
    finally:
        db_session.close()


@app.route("/vials")
@login_required
def vials():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        active_vials = db.list_active_vials()
        return render_template("vials.html", vials=active_vials)
    finally:
        db_session.close()


@app.route("/protocols")
@login_required
def protocols():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        active_protocols = db.list_active_protocols()
        return render_template("protocols.html", protocols=active_protocols)
    finally:
        db_session.close()


@app.route("/history")
@login_required
def history():
    days = request.args.get("days", 30, type=int)
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        injections = db.get_recent_injections(days=days)
        return render_template("history.html", injections=injections, days=days)
    finally:
        db_session.close()


# ==================== COMPARE ====================
@app.route("/compare")
@login_required
def compare():
    """Peptide comparison page."""
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        peptides_all = db.list_peptides()
        return render_template("compare.html", peptides=peptides_all)
    finally:
        db_session.close()


# ==================== API: Recommendations (Age + Goals) ====================
@app.route("/api/recommendations")
@login_required
def api_recommendations():
    """
    Returns a prioritized list for the dashboard "start here" widget.
    This is a UI prioritization tool based on peptide notes/benefits text.
    Not medical advice.
    """
    age = request.args.get("age", 35, type=int)
    goals_raw = request.args.get("goals", "", type=str)  # "fat_loss,recovery"
    goal_set = {g.strip().lower() for g in goals_raw.split(",") if g.strip()}

    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        peptides_all = db.list_peptides()
    finally:
        db_session.close()

    def blob(p) -> str:
        parts = [
            getattr(p, "name", "") or "",
            getattr(p, "common_name", "") or "",
            getattr(p, "benefits", "") or "",
            getattr(p, "notes", "") or "",
        ]
        return " ".join(parts).lower()

    def score_peptide(p) -> int:
        t = blob(p)
        s = 0

        # age heuristics
        if age >= 50:
            if any(k in t for k in ["longevity", "mitochond", "cognition", "recovery", "aging"]):
                s += 2
        elif age < 35:
            if any(k in t for k in ["recovery", "skin", "injury", "collagen"]):
                s += 1

        # goals heuristics
        if "fat_loss" in goal_set and any(k in t for k in ["fat", "weight", "glp", "metabolic", "obesity"]):
            s += 3
        if "recovery" in goal_set and any(k in t for k in ["recovery", "injury", "tendon", "healing", "repair"]):
            s += 3
        if "skin" in goal_set and any(k in t for k in ["skin", "collagen", "cosmetic", "wrinkle"]):
            s += 3
        if "cognition" in goal_set and any(k in t for k in ["cognition", "brain", "nootropic", "neuro"]):
            s += 3
        if "longevity" in goal_set and any(k in t for k in ["longevity", "mitochond", "aging", "healthspan"]):
            s += 3

        return s

    scored = [(score_peptide(p), p) for p in peptides_all]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:6]

    items = []
    for s, p in top:
        items.append(
            {
                "id": p.id,
                "name": p.name,
                "common_name": getattr(p, "common_name", None),
                "score": s,
                "image": getattr(p, "image_filename", None),
            }
        )

    return jsonify({"age": age, "goals": sorted(list(goal_set)), "items": items})


# ==================== API: Vials by peptide ====================
@app.route("/api/vials/<int:peptide_id>")
@login_required
def api_vials_by_peptide(peptide_id):
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    try:
        vials = db.list_active_vials(peptide_id)
        vials_data = [
            {
                "id": v.id,
                "mg_amount": v.mg_amount,
                "concentration": v.concentration_mcg_per_ml,
                "remaining_ml": v.remaining_ml,
            }
            for v in vials
        ]
        return jsonify(vials_data)
    finally:
        db_session.close()


# ==================== AI CHAT ====================
@app.route("/chat")
@login_required
def chat():
    return render_template("chat.html")


@app.route("/coaching")
@login_required
def coaching():
    """Coaching CTA page (Stripe/Calendly wiring can be added later)."""
    return render_template("coaching.html")


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    """Handle AI chat messages."""
    if OpenAI is None:
        return jsonify({"success": False, "error": "OpenAI SDK not installed."}), 500

    try:
        data = request.get_json(silent=True) or {}
        user_message = (data.get("message") or "").strip()
        if not user_message:
            return jsonify({"success": False, "error": "No message provided"}), 400

        db_session = get_session(db_url)
        db = PeptideDB(db_session)
        try:
            protocols = db.list_active_protocols()
            all_peptides = db.list_peptides()
        finally:
            db_session.close()

        user_context = f"User has {len(protocols)} active protocols"
        if protocols:
            protocol_list = ", ".join(
                [f"{p.peptide.name} ({p.dose_mcg}mcg {p.frequency_per_day}x/day)" for p in protocols[:3]]
            )
            user_context += f": {protocol_list}"

        system_prompt = f"""You are an educational assistant for a peptide tracking application.

IMPORTANT SAFETY GUIDELINES:
- Educational information only, not medical advice
- Encourage consulting a licensed clinician
- Do not diagnose or prescribe
- Be conservative about risks/contraindications
- If asked for dosing, provide general ranges and emphasize clinician oversight

AVAILABLE PEPTIDES (sample):
{', '.join([p.name for p in all_peptides[:25]])}

USER CONTEXT:
{user_context}

Keep answers concise (2-4 short paragraphs), clear, and safety-forward.
"""

        api_key = getattr(Config, "OPENAI_API_KEY", None) or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return jsonify({
                "success": False,
                "error": "Missing OPENAI_API_KEY. Set it in your Render service environment variables."
            }), 500

        client = OpenAI(api_key=api_key)

        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=500,
            temperature=0.7,
        )

        assistant_message = resp.choices[0].message.content
        return jsonify({"success": True, "message": assistant_message})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"success": False, "error": "Failed to get AI response. Please try again."}), 500


# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(error):
    return render_template("500.html"), 500



@app.route('/food')
@login_required
def food():
    # CalorieNinjas nutrition search (beta)
    api_key = os.getenv('CALORIENINJAS_API_KEY', '').strip()
    q = request.args.get('q', '').strip()
    items = None
    error = None
    calorieninjas_enabled = bool(api_key)

    if q:
        if not api_key:
            error = "CALORIENINJAS_API_KEY is not set on the server."
        else:
            try:
                resp = requests.get(
                    "https://api.calorieninjas.com/v1/nutrition",
                    params={"query": q},
                    headers={"X-Api-Key": api_key},
                    timeout=15,
                )
                if resp.status_code != 200:
                    error = f"CalorieNinjas error: HTTP {resp.status_code}"
                else:
                    data = resp.json() or {}
                    items = data.get("items", []) or []
            except Exception as e:
                error = f"Could not reach CalorieNinjas: {e}"

    return render_template('food.html', title="Log Food", items=items, error=error, calorieninjas_enabled=calorieninjas_enabled)


if __name__ == "__main__":
    ModelBase.metadata.create_all(engine)
    app.run(debug=True, host="0.0.0.0", port=5000)
