"""
Peptide Tracker Web Application
Flask web interface with session-based auth and tier support

This version is designed to "get it working again" by:
- Ensuring users.tier exists in Postgres (startup-safe migration)
- Injecting current_user + has_endpoint + tier_at_least into Jinja
- Supplying dashboard.html's expected context (`stats`, `protocols`, `recent_injections`)
- Providing stub routes for endpoints referenced in templates to prevent url_for BuildError
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound

from sqlalchemy import Column, Integer, String, DateTime, text
from config import Config
from models import get_session, create_engine, Base as ModelBase

# -------------------------
# Flask app init
# -------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# -------------------------
# User model (define BEFORE create_all)
# -------------------------
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

# -------------------------
# DB init + migration
# -------------------------
db_url = Config.DATABASE_URL
engine = create_engine(db_url)

def ensure_users_tier_column(engine):
    """Add users.tier on legacy Postgres DBs."""
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
        else:
            with engine.begin() as conn:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN tier VARCHAR(20) DEFAULT 'free';"))
                except Exception:
                    pass
    except Exception as e:
        print(f"Warning: could not ensure users.tier column: {e}")

ModelBase.metadata.create_all(engine)
ensure_users_tier_column(engine)

# -------------------------
# Tier helpers
# -------------------------
TIER_ORDER = {"free": 0, "tier1": 1, "tier2": 2, "admin": 3}

def tier_at_least(tier: str, minimum: str) -> bool:
    return TIER_ORDER.get(tier or "free", 0) >= TIER_ORDER.get(minimum, 0)

# -------------------------
# Auth helpers
# -------------------------
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

# -------------------------
# Jinja helpers
# -------------------------
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
        return {
            "current_user": AnonymousUser(),
            "has_endpoint": has_endpoint,
            "tier_at_least": tier_at_least,
        }

    user.is_authenticated = True
    if not getattr(user, "tier", None):
        user.tier = "free"

    return {
        "current_user": user,
        "has_endpoint": has_endpoint,
        "tier_at_least": tier_at_least,
    }

# -------------------------
# Utility: render template if it exists, otherwise redirect
# -------------------------
def render_if_exists(template_name: str, fallback_endpoint: str = "dashboard", **ctx):
    try:
        return render_template(template_name, **ctx)
    except TemplateNotFound:
        return redirect(url_for(fallback_endpoint))

# -------------------------
# Dashboard context
# -------------------------
def _compute_dashboard_context():
    # safe defaults so dashboard never 500s
    stats = {
        "active_protocols": 0,
        "active_vials": 0,
        "injections_this_week": 0,
        "total_peptides": 0,
    }
    protocols = []
    recent_injections = []

    try:
        # If your original DB helper exists, use it; otherwise fallback
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

# -------------------------
# Routes
# -------------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_if_exists("index.html", fallback_endpoint="dashboard")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("register"))

        db = get_session(db_url)
        try:
            existing = db.query(User).filter((User.username == username) | (User.email == email)).first()
            if existing:
                flash("Username or email already exists.", "danger")
                return redirect(url_for("register"))

            user = User(username=username, email=email, tier="free")
            user.set_password(password)
            db.add(user)
            db.commit()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        finally:
            db.close()

    return render_if_exists("register.html", fallback_endpoint="login")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        db = get_session(db_url)
        try:
            user = db.query(User).filter_by(username=username).first()
            if user and user.check_password(password):
                session["user_id"] = user.id
                flash("Logged in successfully.", "success")
                return redirect(url_for("dashboard"))
        finally:
            db.close()

        flash("Invalid credentials.", "danger")

    return render_if_exists("login.html", fallback_endpoint="index")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    stats, protocols, recent_injections = _compute_dashboard_context()
    return render_if_exists(
        "dashboard.html",
        stats=stats,
        protocols=protocols,
        recent_injections=(recent_injections[:5] if isinstance(recent_injections, list) else recent_injections),
    )

# -------------------------
# Endpoints referenced by templates (stubs so url_for won't crash)
# -------------------------
@app.route("/log-injection", methods=["GET", "POST"])
@login_required
def log_injection():
    # You can build this page later; for now it won't crash the dashboard button.
    if request.method == "POST":
        flash("Injection logging is not wired yet (stub).", "info")
        return redirect(url_for("dashboard"))
    return render_if_exists("log_injection.html", fallback_endpoint="dashboard")

@app.route("/peptides")
@login_required
def peptides():
    return render_if_exists("peptides.html", fallback_endpoint="dashboard")

@app.route("/calculator")
@login_required
def calculator():
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
