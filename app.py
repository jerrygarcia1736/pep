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


# -------------------------
# Jinja-safe current_user injection  ✅ FIX
# -------------------------
class AnonymousUser:
    is_authenticated = False
    id = None
    username = None
    email = None


@app.context_processor
def inject_current_user():
    user = get_current_user()
    if user is None:
        return {"current_user": AnonymousUser()}
    setattr(user, "is_authenticated", True)
    return {"current_user": user}


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

# (rest of file unchanged)
