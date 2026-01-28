"""
Peptide Tracker Web Application
Flask web interface with user authentication + dosing calculator + chat.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
from datetime import datetime
import os

from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy import Column, Integer, String, DateTime, create_engine
from models import get_session
from models import Base as ModelBase

from database import PeptideDB
from calculator import PeptideCalculator
from config import Config

# OpenAI (openai>=1.0.0)
from openai import OpenAI


# -------------------- User model --------------------
class User(ModelBase):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


# -------------------- App setup --------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

db_url = Config.DATABASE_URL
print(f"Using database: {db_url[:25]}...")

engine = create_engine(db_url)
ModelBase.metadata.create_all(engine)

# OpenAI client (only if key exists)
openai_client = OpenAI(api_key=Config.OPENAI_API_KEY) if Config.OPENAI_API_KEY else None


# Optional: seed on deploy when RUN_SEED=true (idempotent)
def maybe_seed_database():
    if os.getenv("RUN_SEED", "").lower() != "true":
        return
    try:
        from seed_data import seed_common_peptides
        print("RUN_SEED=true -> seeding peptides (idempotent)...")
        s = get_session(db_url)
        seed_common_peptides(s)
        s.close()
        print("Seeding finished.")
    except Exception as e:
        print(f"Warning: seeding failed: {e}")

maybe_seed_database()


# -------------------- Auth helpers --------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# -------------------- Routes --------------------
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not username or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('register'))

        db_session = get_session(db_url)
        existing_user = db_session.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()

        if existing_user:
            flash('Username or email already exists.', 'danger')
            db_session.close()
            return redirect(url_for('register'))

        user = User(username=username, email=email)
        user.set_password(password)
        db_session.add(user)
        db_session.commit()

        flash('Registration successful! Please log in.', 'success')
        db_session.close()
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        db_session = get_session(db_url)
        user = db_session.query(User).filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash(f'Welcome back, {user.username}!', 'success')
            db_session.close()
            return redirect(url_for('dashboard'))

        flash('Invalid username or password.', 'danger')
        db_session.close()

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)

    active_protocols = db.list_active_protocols()
    recent_injections = db.get_recent_injections(days=7)
    active_vials = db.list_active_vials()

    stats = {
        'active_protocols': len(active_protocols),
        'active_vials': len(active_vials),
        'injections_this_week': len(recent_injections),
        'total_peptides': len(db.list_peptides())
    }

    db_session.close()

    return render_template(
        'dashboard.html',
        stats=stats,
        protocols=active_protocols,
        recent_injections=recent_injections[:5]
    )


@app.route('/peptides')
@login_required
def peptides():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    all_peptides = db.list_peptides()
    db_session.close()
    return render_template('peptides.html', peptides=all_peptides)


@app.route('/calculator', methods=['GET', 'POST'])
@login_required
def calculator():
    result = None
    if request.method == 'POST':
        try:
            peptide_name = request.form.get('peptide_name')
            mg_amount = float(request.form.get('mg_amount'))
            ml_water = float(request.form.get('ml_water'))
            dose_mcg = float(request.form.get('dose_mcg'))
            doses_per_day = int(request.form.get('doses_per_day'))

            result = PeptideCalculator.full_reconstitution_report(
                peptide_name, mg_amount, ml_water, dose_mcg, doses_per_day
            )
        except (ValueError, TypeError) as e:
            flash(f'Invalid input: {e}', 'danger')

    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    peptides_list = db.list_peptides()
    db_session.close()

    return render_template('calculator.html', result=result, peptides=peptides_list)



# -------------------- Vials --------------------
@app.route('/vials')
@login_required
def vials():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    active_vials = db.list_active_vials()
    peptides_list = db.list_peptides()
    db_session.close()
    return render_template('vials.html', vials=active_vials, peptides=peptides_list)


@app.route('/vials/add', methods=['GET', 'POST'])
@login_required
def add_vial():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    peptides_list = db.list_peptides()

    if request.method == 'POST':
        try:
            peptide_id = int(request.form.get('peptide_id'))
            mg_amount = float(request.form.get('mg_amount'))
            bacteriostatic_water_ml = request.form.get('bacteriostatic_water_ml')
            bacteriostatic_water_ml = float(bacteriostatic_water_ml) if bacteriostatic_water_ml else None

            lot_number = (request.form.get('lot_number') or '').strip() or None
            vendor = (request.form.get('vendor') or '').strip() or None
            cost = request.form.get('cost')
            cost = float(cost) if cost else None
            notes = (request.form.get('notes') or '').strip() or None

            db.add_vial(
                peptide_id=peptide_id,
                mg_amount=mg_amount,
                bacteriostatic_water_ml=bacteriostatic_water_ml,
                lot_number=lot_number,
                vendor=vendor,
                cost=cost,
                notes=notes,
            )
            flash('Vial added successfully.', 'success')
            db_session.close()
            return redirect(url_for('vials'))
        except Exception as e:
            flash(f'Error adding vial: {e}', 'danger')

    db_session.close()
    return render_template('add_vial.html', peptides=peptides_list)


# -------------------- Protocols --------------------
@app.route('/protocols')
@login_required
def protocols():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    active_protocols = db.list_active_protocols()
    peptides_list = db.list_peptides()
    db_session.close()
    return render_template('protocols.html', protocols=active_protocols, peptides=peptides_list)


@app.route('/protocols/add', methods=['GET', 'POST'])
@login_required
def add_protocol():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    peptides_list = db.list_peptides()

    if request.method == 'POST':
        try:
            peptide_id = int(request.form.get('peptide_id'))
            name = (request.form.get('name') or '').strip() or 'Protocol'
            dose_mcg = float(request.form.get('dose_mcg'))
            frequency_per_day = int(request.form.get('frequency_per_day'))
            description = (request.form.get('description') or '').strip() or None
            duration_days = request.form.get('duration_days')
            duration_days = int(duration_days) if duration_days else None
            goals = (request.form.get('goals') or '').strip() or None
            notes = (request.form.get('notes') or '').strip() or None

            db.create_protocol(
                peptide_id=peptide_id,
                name=name,
                dose_mcg=dose_mcg,
                frequency_per_day=frequency_per_day,
                description=description,
                duration_days=duration_days,
                goals=goals,
                notes=notes,
            )
            flash('Protocol created successfully.', 'success')
            db_session.close()
            return redirect(url_for('protocols'))
        except Exception as e:
            flash(f'Error creating protocol: {e}', 'danger')

    db_session.close()
    return render_template('add_protocol.html', peptides=peptides_list)


@app.route('/protocol/<int:protocol_id>')
@login_required
def protocol_detail(protocol_id: int):
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    protocol = db.get_protocol(protocol_id)
    db_session.close()
    if not protocol:
        flash('Protocol not found.', 'warning')
        return redirect(url_for('protocols'))
    return render_template('protocol_detail.html', protocol=protocol)


# -------------------- History / Injections --------------------
@app.route('/history')
@login_required
def history():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    injections = db.get_recent_injections(days=30)
    peptides_list = db.list_peptides()
    db_session.close()
    return render_template('history.html', injections=injections, peptides=peptides_list)


@app.route('/injections/log', methods=['GET', 'POST'])
@login_required
def log_injection():
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    peptides_list = db.list_peptides()
    active_protocols = db.list_active_protocols()
    active_vials = db.list_active_vials()

    if request.method == 'POST':
        try:
            peptide_id = int(request.form.get('peptide_id'))
            dose_mcg = float(request.form.get('dose_mcg'))
            protocol_id = request.form.get('protocol_id')
            protocol_id = int(protocol_id) if protocol_id else None
            vial_id = request.form.get('vial_id')
            vial_id = int(vial_id) if vial_id else None
            notes = (request.form.get('notes') or '').strip() or None

            db.log_injection(
                peptide_id=peptide_id,
                dose_mcg=dose_mcg,
                protocol_id=protocol_id,
                vial_id=vial_id,
                notes=notes,
            )
            flash('Injection logged.', 'success')
            db_session.close()
            return redirect(url_for('history'))
        except Exception as e:
            flash(f'Error logging injection: {e}', 'danger')

    db_session.close()
    return render_template(
        'log_injection.html',
        peptides=peptides_list,
        protocols=active_protocols,
        vials=active_vials
    )


@app.route('/peptide/<int:peptide_id>')
@login_required
def peptide_detail(peptide_id: int):
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    peptide = db.get_peptide(peptide_id)
    db_session.close()
    if not peptide:
        flash('Peptide not found.', 'warning')
        return redirect(url_for('peptides'))
    return render_template('peptide_detail.html', peptide=peptide)



# -------------------- Chat --------------------
@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html')


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    if openai_client is None:
        return jsonify({
            "success": False,
            "error": "Chat is not configured. Set OPENAI_API_KEY in Render environment variables."
        }), 500

    data = request.get_json() or {}
    user_message = (data.get('message') or '').strip()
    if not user_message:
        return jsonify({'success': False, 'error': 'No message provided'}), 400

    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    protocols = db.list_active_protocols()
    all_peptides = db.list_peptides()
    db_session.close()

    protocol_summary = "No active protocols."
    if protocols:
        protocol_summary = "; ".join(
            [f"{p.peptide.name}: {p.dose_mcg}mcg, {p.frequency_per_day}x/day" for p in protocols[:10]]
        )

    system_prompt = f"""
You are a helpful assistant inside a peptide tracking app.

Rules:
- Provide general educational information only.
- Do NOT provide personalized medical advice or dosing instructions.
- Encourage consulting a licensed clinician for medical decisions.
- You can explain what the user has logged, summarize protocols, and answer questions about app features.

User’s active protocols:
{protocol_summary}

Peptides available in database (names):
{", ".join([p.name for p in all_peptides])}
""".strip()

    try:
        resp = openai_client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=400,
            temperature=0.5,
        )
        assistant_message = resp.choices[0].message.content
        return jsonify({"success": True, "message": assistant_message})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"success": False, "error": "AI request failed. Check server logs."}), 500


# -------------------- Error handlers --------------------
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(error):
    return render_template('500.html'), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=True, host="0.0.0.0", port=port)
