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

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound

from sqlalchemy import Column, Integer, String, DateTime, Float, text
from config import Config
from models import get_session, create_engine, Base as ModelBase

# Import nutrition API
from nutrition_api import register_nutrition_routes
from confidence import compute_injection_confidence


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

@app.route("/scan-food", methods=["GET"])
@login_required
def scan_food():
    # Posts recognized food directly into /log-food via form POST (no template changes needed)
    html = """<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Scan Food</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; margin:16px; background:#f7f7fb;}
    .card{background:#fff;border:1px solid #e6e6ef;border-radius:14px;padding:14px;box-shadow:0 1px 8px rgba(0,0,0,.04); max-width:720px; margin:0 auto;}
    h1{font-size:20px;margin:0 0 6px;}
    .muted{color:#666;font-size:13px;line-height:1.4}
    .tabs{display:flex; gap:8px; margin:14px 0;}
    .tab{flex:1; padding:10px 12px; border-radius:12px; border:1px solid #e6e6ef; background:#fafafe; cursor:pointer; font-weight:600;}
    .tab.active{background:#eef2ff; border-color:#c7d2fe;}
    .panel{display:none; margin-top:10px;}
    .panel.active{display:block;}
    input[type=file]{width:100%;}
    .btn{display:inline-flex;align-items:center;justify-content:center; gap:8px; padding:10px 12px; border-radius:12px; border:1px solid #d9d9e6; background:#111827; color:#fff; font-weight:700; cursor:pointer;}
    .btn.secondary{background:#fff;color:#111827;}
    .btn:disabled{opacity:.5;cursor:not-allowed;}
    .row{display:flex; gap:10px; flex-wrap:wrap; margin-top:10px;}
    .chip{padding:8px 10px; border-radius:999px; border:1px solid #e6e6ef; background:#fff; cursor:pointer;}
    .box{border:1px dashed #d9d9e6; border-radius:12px; padding:10px; background:#fafafe; margin-top:10px;}
    img{max-width:100%; border-radius:12px; border:1px solid #e6e6ef;}
    textarea{width:100%; min-height:90px; padding:10px; border-radius:12px; border:1px solid #e6e6ef;}
    .toplinks{display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end;}
    .linkbtn{display:inline-flex;align-items:center;gap:8px;padding:8px 10px;border-radius:12px;border:1px solid #e6e6ef;background:#fff;text-decoration:none;color:#111827;font-weight:700;}
  </style>
</head>
<body>
  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
      <div>
        <h1>📸 Scan Food</h1>
        <div class="muted">Snap a photo of the food for a best-guess label, or use OCR for receipts/labels. You’ll confirm before logging.</div>
      </div>
      <div class="toplinks">
        <a class="linkbtn" href="/nutrition">🍎 Nutrition</a>
        <a class="linkbtn" href="/pep-ai">🤖 Pep AI</a>
      </div>
    </div>

    <div class="tabs">
      <button class="tab active" id="tab-photo" type="button">Photo (AI Guess)</button>
      <button class="tab" id="tab-ocr" type="button">Text (OCR)</button>
    </div>

    <div class="panel active" id="panel-photo">
      <div class="box"><div class="muted"><b>Tip:</b> Fill the frame with the food. Good lighting helps.</div></div>
      <div style="margin-top:10px;">
        <input id="foodPhoto" type="file" accept="image/*" capture="environment" capture="environment" />
      
          <div class="mt-3">
            <div class="d-flex flex-wrap gap-2">
              <button type="button" class="btn btn-outline-primary" id="openFoodCameraBtn">
                <i class="bi bi-camera"></i> Use Camera
              </button>
              <button type="button" class="btn btn-outline-secondary d-none" id="captureFoodFrameBtn">
                <i class="bi bi-circle-fill"></i> Capture Photo
              </button>
              <button type="button" class="btn btn-outline-danger d-none" id="stopFoodCameraBtn">
                <i class="bi bi-x-circle"></i> Stop
              </button>
            </div>

            <div class="mt-3 d-none" id="foodCameraWrap">
              <video id="foodCameraStream" playsinline autoplay class="w-100 rounded border"></video>
              <canvas id="foodCameraCanvas" class="d-none"></canvas>
            </div>
          </div>
</div>
      <div id="photoPreview" style="margin-top:10px; display:none;">
        <img id="previewImg" />
      </div>

      <div class="row">
        <button class="btn" id="btnGuess" type="button" disabled>🤖 Guess Food</button>
        <button class="btn secondary" id="btnClear" type="button" disabled>Clear</button>
      </div>

      <div id="guessBox" class="box" style="display:none;">
        <div class="muted" style="margin-bottom:6px;"><b>Tap a guess to log:</b></div>
        <div id="guessChips" class="row"></div>
      </div>
    </div>

    <div class="panel" id="panel-ocr">
      <div class="box"><div class="muted"><b>Use OCR</b> for receipts, labels, or written notes (e.g., “apple, 1 medium”).</div></div>
      <div style="margin-top:10px;">
        <input id="ocrPhoto" type="file" accept="image/*" capture="environment" />
      </div>
      <div class="row">
        <button class="btn" id="btnOcr" type="button" disabled>🔎 Extract Text</button>
      </div>
      <div style="margin-top:10px;">
        <textarea id="ocrText" placeholder="OCR text will appear here..."></textarea>
      </div>
      <div class="row">
        <button class="btn" id="btnLogOcr" type="button" disabled>✅ Log This Text</button>
      </div>
    </div>

    <form id="logFoodForm" method="post" action="/log-food" style="display:none;">
      <input type="hidden" name="food_description" id="food_description" value="" />
    </form>
  </div>

  <!-- TFJS + MobileNet (open source, browser-side) -->
  <script src="https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.21.0/dist/tf.min.js">
      // --- Mobile camera support (direct capture) ---
      let cameraStream = null;

      async function startCamera() {
        const wrap = document.getElementById('cameraWrap');
        const video = document.getElementById('cameraStream');
        const openBtn = document.getElementById('openCameraBtn');
        const capBtn = document.getElementById('captureFrameBtn');
        const stopBtn = document.getElementById('stopCameraBtn');

        try {
          cameraStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: "environment" } },
            audio: false
          });
          video.srcObject = cameraStream;
          wrap.classList.remove('d-none');
          capBtn.classList.remove('d-none');
          stopBtn.classList.remove('d-none');
          openBtn.classList.add('d-none');
        } catch (e) {
          console.error(e);
          alert("Could not access camera. You can still use the Upload Photo option.");
        }
      }

      function stopCamera() {
        const wrap = document.getElementById('cameraWrap');
        const openBtn = document.getElementById('openCameraBtn');
        const capBtn = document.getElementById('captureFrameBtn');
        const stopBtn = document.getElementById('stopCameraBtn');
        const video = document.getElementById('cameraStream');

        if (cameraStream) {
          cameraStream.getTracks().forEach(t => t.stop());
          cameraStream = null;
        }
        video.srcObject = null;
        wrap.classList.add('d-none');
        capBtn.classList.add('d-none');
        stopBtn.classList.add('d-none');
        openBtn.classList.remove('d-none');
      }

      function capturePhotoToFileInput() {
        const video = document.getElementById('cameraStream');
        const canvas = document.getElementById('cameraCanvas');
        const input = document.getElementById('peptidePhoto');

        const w = video.videoWidth || 1280;
        const h = video.videoHeight || 720;
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, w, h);

        canvas.toBlob(blob => {
          if (!blob) return;
          // Create a File and set it to the file input so existing OCR flow works.
          const file = new File([blob], "camera.jpg", { type: "image/jpeg" });
          const dt = new DataTransfer();
          dt.items.add(file);
          input.files = dt.files;

          // Trigger the same handler as upload selection.
          const evt = new Event('change', { bubbles: true });
          input.dispatchEvent(evt);

          stopCamera();
        }, "image/jpeg", 0.92);
      }

      document.getElementById('openCameraBtn')?.addEventListener('click', startCamera);
      document.getElementById('stopCameraBtn')?.addEventListener('click', stopCamera);
      document.getElementById('captureFrameBtn')?.addEventListener('click', capturePhotoToFileInput);
      // Auto-open camera ONLY when arriving via nav click (?autocam=1) and only once per session for this page.
      window.addEventListener('DOMContentLoaded', () => {
        const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || window.matchMedia('(max-width: 768px)').matches;
        if (!isMobile) return;

        const params = new URLSearchParams(window.location.search);
        const wantsAuto = params.get('autocam') === '1';
        if (!wantsAuto) return;

        const key = 'autocam_once:/scan-peptides';
        if (sessionStorage.getItem(key) === '1') return;

        // Mark as used and remove the query param so refresh/back won't retrigger.
        sessionStorage.setItem(key, '1');
        try {
          params.delete('autocam');
          const newUrl = window.location.pathname + (params.toString() ? ('?' + params.toString()) : '') + window.location.hash;
          history.replaceState(null, '', newUrl);
        } catch (e) {}

        setTimeout(() => { startCamera(); }, 350);
      });
// --- Mobile camera support (direct capture) for Food ---
      let foodCameraStreamObj = null;

      async function startFoodCamera() {
        const wrap = document.getElementById('foodCameraWrap');
        const video = document.getElementById('foodCameraStream');
        const openBtn = document.getElementById('openFoodCameraBtn');
        const capBtn = document.getElementById('captureFoodFrameBtn');
        const stopBtn = document.getElementById('stopFoodCameraBtn');

        try {
          foodCameraStreamObj = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: "environment" } },
            audio: false
          });
          video.srcObject = foodCameraStreamObj;
          wrap.classList.remove('d-none');
          capBtn.classList.remove('d-none');
          stopBtn.classList.remove('d-none');
          openBtn.classList.add('d-none');
        } catch (e) {
          console.error(e);
          alert("Could not access camera. You can still use the Upload Photo option.");
        }
      }

      function stopFoodCamera() {
        const wrap = document.getElementById('foodCameraWrap');
        const openBtn = document.getElementById('openFoodCameraBtn');
        const capBtn = document.getElementById('captureFoodFrameBtn');
        const stopBtn = document.getElementById('stopFoodCameraBtn');
        const video = document.getElementById('foodCameraStream');

        if (foodCameraStreamObj) {
          foodCameraStreamObj.getTracks().forEach(t => t.stop());
          foodCameraStreamObj = null;
        }
        video.srcObject = null;
        wrap.classList.add('d-none');
        capBtn.classList.add('d-none');
        stopBtn.classList.add('d-none');
        openBtn.classList.remove('d-none');
      }

      function captureFoodPhotoToFileInput() {
        const video = document.getElementById('foodCameraStream');
        const canvas = document.getElementById('foodCameraCanvas');
        const input = document.getElementById('foodPhoto');

        const w = video.videoWidth || 1280;
        const h = video.videoHeight || 720;
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, w, h);

        canvas.toBlob(blob => {
          if (!blob) return;
          const file = new File([blob], "food_camera.jpg", { type: "image/jpeg" });
          const dt = new DataTransfer();
          dt.items.add(file);
          input.files = dt.files;

          const evt = new Event('change', { bubbles: true });
          input.dispatchEvent(evt);

          stopFoodCamera();
        }, "image/jpeg", 0.92);
      }

      document.getElementById('openFoodCameraBtn')?.addEventListener('click', startFoodCamera);
      document.getElementById('stopFoodCameraBtn')?.addEventListener('click', stopFoodCamera);
      document.getElementById('captureFoodFrameBtn')?.addEventListener('click', captureFoodPhotoToFileInput);
    
</script>
  <script src="https://cdn.jsdelivr.net/npm/@tensorflow-models/mobilenet@2.1.1/dist/mobilenet.min.js"></script>

  <!-- Tesseract.js (open source OCR, browser-side) -->
  <script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>

  <script>
    const tabPhoto = document.getElementById("tab-photo");
    const tabOcr   = document.getElementById("tab-ocr");
    const panelPhoto = document.getElementById("panel-photo");
    const panelOcr   = document.getElementById("panel-ocr");

    function activate(which){
      const isPhoto = which === "photo";
      tabPhoto.classList.toggle("active", isPhoto);
      tabOcr.classList.toggle("active", !isPhoto);
      panelPhoto.classList.toggle("active", isPhoto);
      panelOcr.classList.toggle("active", !isPhoto);
    }
    tabPhoto.addEventListener("click", () => activate("photo"));
    tabOcr.addEventListener("click", () => activate("ocr"));

    // ---- Photo (AI Guess) ----
    const foodPhoto = document.getElementById("foodPhoto");
    const preview = document.getElementById("photoPreview");
    const previewImg = document.getElementById("previewImg");
    const btnGuess = document.getElementById("btnGuess");
    const btnClear = document.getElementById("btnClear");
    const guessBox = document.getElementById("guessBox");
    const guessChips = document.getElementById("guessChips");

    let model = null;
    let imgEl = null;

    foodPhoto.addEventListener("change", async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      const url = URL.createObjectURL(file);
      previewImg.src = url;
      preview.style.display = "block";
      btnGuess.disabled = false;
      btnClear.disabled = false;
      guessBox.style.display = "none";
      guessChips.innerHTML = "";

      imgEl = new Image();
      imgEl.src = url;
      await new Promise(res => imgEl.onload = res);
    });

    btnClear.addEventListener("click", () => {
      foodPhoto.value = "";
      preview.style.display = "none";
      btnGuess.disabled = true;
      btnClear.disabled = true;
      guessBox.style.display = "none";
      guessChips.innerHTML = "";
      imgEl = null;
    });

    function normalizeLabel(label){
      label = (label || "").toLowerCase();
      if (label.includes("apple")) return "apple";
      if (label.includes("banana")) return "banana";
      if (label.includes("orange")) return "orange";
      if (label.includes("egg")) return "egg";
      if (label.includes("pizza")) return "pizza";
      if (label.includes("hamburger") || label.includes("cheeseburger")) return "hamburger";
      return label.split(",")[0].split(" ")[0].trim();
    }

    btnGuess.addEventListener("click", async () => {
      if (!imgEl) return;

      btnGuess.disabled = true;
      btnGuess.textContent = "Loading model...";
      try{
        if (!model) model = await mobilenet.load();
        btnGuess.textContent = "Analyzing...";
        const preds = await model.classify(imgEl);

        guessChips.innerHTML = "";
        preds.slice(0,5).forEach(p => {
          const term = normalizeLabel(p.className);
          const chip = document.createElement("div");
          chip.className = "chip";
          chip.textContent = `${term} (${Math.round(p.probability*100)}%)`;
          chip.addEventListener("click", () => {
            document.getElementById("food_description").value = term;
            document.getElementById("logFoodForm").submit();
          });
          guessChips.appendChild(chip);
        });

        guessBox.style.display = "block";
      }catch(err){
        alert("Food guess failed. Try again with better lighting and closer framing.");
      }finally{
        btnGuess.disabled = false;
        btnGuess.textContent = "🤖 Guess Food";
      }
    });

    // ---- OCR (Text) ----
    const ocrPhoto = document.getElementById("ocrPhoto");
    const btnOcr = document.getElementById("btnOcr");
    const ocrText = document.getElementById("ocrText");
    const btnLogOcr = document.getElementById("btnLogOcr");

    ocrPhoto.addEventListener("change", () => {
      const file = ocrPhoto.files && ocrPhoto.files[0];
      btnOcr.disabled = !file;
      btnLogOcr.disabled = true;
      ocrText.value = "";
    });

    btnOcr.addEventListener("click", async () => {
      const file = ocrPhoto.files && ocrPhoto.files[0];
      if (!file) return;

      btnOcr.disabled = true;
      btnOcr.textContent = "Running OCR...";
      try{
        const { data } = await Tesseract.recognize(file, "eng");
        const text = (data && data.text) ? data.text.trim() : "";
        ocrText.value = text;
        btnLogOcr.disabled = text.length < 2;
      }catch(err){
        alert("OCR failed. Try again with brighter lighting and closer focus.");
      }finally{
        btnOcr.disabled = false;
        btnOcr.textContent = "🔎 Extract Text";
      }
    });

    btnLogOcr.addEventListener("click", () => {
      const text = (ocrText.value || "").trim();
      if (!text) return;
      document.getElementById("food_description").value = text;
      document.getElementById("logFoodForm").submit();
    });
  </script>
</body>
</html>"""
    return render_template_string(html)



@app.route("/scan-nutrition", methods=["GET"])
@login_required
def scan_nutrition():
    # Alias route for clarity in the top nav; use existing Nutrition page.
    return redirect(url_for("nutrition")) if has_endpoint("nutrition") else redirect("/nutrition")


@app.route("/scan-peptides", methods=["GET"])
@login_required
def scan_peptides():
    peptides = _load_peptides_list()
    peptide_names = [p.get("name","") for p in peptides if p.get("name")]

    html = """<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Scan Peptides</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; margin:16px; background:#f7f7fb;}
    .card{background:#fff;border:1px solid #e6e6ef;border-radius:14px;padding:14px;box-shadow:0 1px 8px rgba(0,0,0,.04); max-width:720px; margin:0 auto;}
    h1{font-size:20px;margin:0 0 6px;}
    .muted{color:#666;font-size:13px;line-height:1.4}
    input[type=file]{width:100%;}
    .btn{display:inline-flex;align-items:center;justify-content:center; gap:8px; padding:10px 12px; border-radius:12px; border:1px solid #d9d9e6; background:#111827; color:#fff; font-weight:700; cursor:pointer;}
    .btn:disabled{opacity:.5;cursor:not-allowed;}
    .box{border:1px dashed #d9d9e6; border-radius:12px; padding:10px; background:#fafafe; margin-top:10px;}
    textarea{width:100%; min-height:90px; padding:10px; border-radius:12px; border:1px solid #e6e6ef;}
    .row{display:flex; gap:10px; flex-wrap:wrap; margin-top:10px;}
    .chip{padding:8px 10px; border-radius:999px; border:1px solid #e6e6ef; background:#fff; cursor:pointer;}
    .toplinks{display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end;}
    .linkbtn{display:inline-flex;align-items:center;gap:8px;padding:8px 10px;border-radius:12px;border:1px solid #e6e6ef;background:#fff;text-decoration:none;color:#111827;font-weight:700;}
  </style>
</head>
<body>
  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
      <div>
        <h1>📦 Scan Peptides</h1>
        <div class="muted">Take a photo of the box/kit label (handwritten or printed). We’ll extract text and suggest peptide matches.</div>
      </div>
      <div class="toplinks">
        <a class="linkbtn" href="/add-vial">➕ Add Vial</a>
        <a class="linkbtn" href="/pep-ai">🤖 Pep AI</a>
      </div>
    </div>

    <div class="box"><div class="muted"><b>Tip:</b> Get close, fill the frame with the writing, and use bright light.</div></div>

    <div style="margin-top:10px;">
      <input id="pepPhoto" type="file" accept="image/*" capture="environment" />
    </div>

    <div class="row">
      <button class="btn" id="btnOcrPep" type="button" disabled>🔎 OCR Label</button>
    </div>

    <div style="margin-top:10px;">
      <textarea id="pepText" placeholder="OCR text will appear here..."></textarea>
    </div>

    <div id="matchBox" class="box" style="display:none;">
      <div class="muted" style="margin-bottom:6px;"><b>Tap a suggested peptide:</b></div>
      <div id="matchChips" class="row"></div>
      <div class="muted" style="margin-top:8px;">This will take you to <b>Add Vial</b> with a reminder to select this peptide.</div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>
  <script>
    const peptideNames = {{ peptide_names | tojson }};
    const pepPhoto = document.getElementById("pepPhoto");
    const btn = document.getElementById("btnOcrPep");
    const pepText = document.getElementById("pepText");
    const matchBox = document.getElementById("matchBox");
    const matchChips = document.getElementById("matchChips");

    pepPhoto.addEventListener("change", () => {
      const file = pepPhoto.files && pepPhoto.files[0];
      btn.disabled = !file;
      pepText.value = "";
      matchBox.style.display = "none";
      matchChips.innerHTML = "";
    });

    function normalize(s){
      return (s||"").toUpperCase().replace(/[^A-Z0-9\-\s]/g," ").replace(/\s+/g," ").trim();
    }

    function scoreMatch(text, name){
      const t = normalize(text);
      const n = normalize(name);
      if (!t || !n) return 0;
      if (t.includes(n)) return 100;
      const tset = new Set(t.split(" "));
      const nset = new Set(n.split(" "));
      let overlap = 0;
      for (const tok of nset){ if (tset.has(tok)) overlap++; }
      return overlap;
    }

    function buildSuggestions(text){
      const scored = peptideNames.map(n => ({name:n, score: scoreMatch(text,n)}))
                                .filter(x => x.score > 0)
                                .sort((a,b) => b.score - a.score)
                                .slice(0,8);
      return scored;
    }

    btn.addEventListener("click", async () => {
      const file = pepPhoto.files && pepPhoto.files[0];
      if (!file) return;

      btn.disabled = true;
      btn.textContent = "Running OCR...";
      try{
        const { data } = await Tesseract.recognize(file, "eng");
        const text = (data && data.text) ? data.text.trim() : "";
        pepText.value = text;

        const suggestions = buildSuggestions(text);
        matchChips.innerHTML = "";

        if (suggestions.length){
          suggestions.forEach(s => {
            const chip = document.createElement("div");
            chip.className = "chip";
            chip.textContent = s.name;
            chip.addEventListener("click", () => {
              const u = new URL(window.location.origin + "/add-vial");
              u.searchParams.set("suggest_peptide", s.name);
              window.location.href = u.toString();
            });
            matchChips.appendChild(chip);
          });
          matchBox.style.display = "block";
        } else {
          matchBox.style.display = "block";
          matchChips.innerHTML = "<div class='muted'>No confident match found — try a closer photo, or just go to Add Vial and select manually.</div>";
        }

      }catch(err){
        alert("OCR failed. Try again with brighter lighting and closer focus.");
      }finally{
        btn.disabled = false;
        btn.textContent = "🔎 OCR Label";
      }
    });
  </script>
</body>
</html>"""
    return render_template_string(html, peptide_names=peptide_names)


@app.before_request
def _scan_hint_flash():
    try:
        if request.method == "GET" and request.path == "/add-vial":
            sugg = (request.args.get("suggest_peptide") or "").strip()
            if sugg:
                flash(f"Scan suggestion: {sugg}. Please select it below (and enter mg amount).", "info")
    except Exception:
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
    """Profile setup (optional).

    This page is intentionally lightweight on mobile:
    - Users can skip at any time
    - The minimal profile captures only 'goals' for Pep AI personalization
    """
    db = get_session(db_url)
    try:
        profile = db.query(UserProfile).filter_by(user_id=session["user_id"]).first()

        if request.method == "POST":
            # Allow skip immediately (matches the template's submit button)
            if (request.form.get("action") or "").strip().lower() == "skip":
                return redirect(url_for("profile_skip"))

            goals = request.form.getlist("goals") or []

            if not goals:
                flash("Please select at least one goal (or tap Skip for now).", "warning")
                return render_if_exists("profile_setup.html", fallback_endpoint="dashboard", profile=profile)

            if profile:
                profile.goals = json.dumps(goals)
                profile.completed_at = datetime.utcnow()
                profile.updated_at = datetime.utcnow()
                flash("Profile saved.", "success")
            else:
                profile = UserProfile(
                    user_id=session["user_id"],
                    goals=json.dumps(goals),
                    completed_at=datetime.utcnow(),
                )
                db.add(profile)
                flash("Profile saved.", "success")

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

