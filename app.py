"""
Peptide Tracker Web Application
Flask web interface with user authentication
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
from datetime import datetime, timedelta
import os
from werkzeug.security import generate_password_hash, check_password_hash
import openai

from models import get_session, Base, create_engine
from database import PeptideDB
from calculator import PeptideCalculator
from config import Config

# Import models for user management
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from models import Base as ModelBase

# User model
class User(ModelBase):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# OpenAI setup
openai.api_key = Config.OPENAI_API_KEY

# Database setup - use DATABASE_URL from Config (works with both PostgreSQL and SQLite)
db_url = Config.DATABASE_URL
print(f"Using database: {db_url[:20]}...")  # Print first 20 chars for debugging

engine = create_engine(db_url)
ModelBase.metadata.create_all(engine)

# Initialize database with peptides if empty (for first deploy)
def init_database():
    """Initialize database with peptides on first run"""
    from seed_data import seed_common_peptides
    session = get_session(db_url)
    from database import PeptideDB
    db = PeptideDB(session)
    
    # Check if database is empty
    peptide_count = len(db.list_peptides())
    if peptide_count == 0:
        print("Database is empty, seeding with common peptides...")
        seed_common_peptides(session)
        print(f"Seeded {len(db.list_peptides())} peptides")
    else:
        print(f"Database already has {peptide_count} peptides")
    
    session.close()

# Initialize on startup
try:
    init_database()
except Exception as e:
    print(f"Warning: Could not initialize database: {e}")


# Login decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# Helper function to get current user
def get_current_user():
    if 'user_id' in session:
        db_session = get_session(db_url)
        user = db_session.query(User).filter_by(id=session['user_id']).first()
        db_session.close()
        return user
    return None


# ==================== AUTHENTICATION ROUTES ====================

@app.route('/')
def index():
    """Landing page"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if not username or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))
        
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('register'))
        
        # Create user
        db_session = get_session(db_url)
        
        # Check if user exists
        existing_user = db_session.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            flash('Username or email already exists.', 'danger')
            db_session.close()
            return redirect(url_for('register'))
        
        # Create new user
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
    """User login"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
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
    """User logout"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ==================== MAIN APPLICATION ROUTES ====================

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard"""
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    # Get stats
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
    
    return render_template('dashboard.html', 
                         stats=stats, 
                         protocols=active_protocols,
                         recent_injections=recent_injections[:5])


@app.route('/peptides')
@login_required
def peptides():
    """List all peptides"""
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    all_peptides = db.list_peptides()
    db_session.close()
    
    return render_template('peptides.html', peptides=all_peptides)


@app.route('/peptides/<int:peptide_id>')
@login_required
def peptide_detail(peptide_id):
    """View peptide details"""
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    peptide = db.get_peptide(peptide_id)
    if not peptide:
        flash('Peptide not found.', 'danger')
        return redirect(url_for('peptides'))
    
    research = db.get_peptide_research(peptide_id)
    
    db_session.close()
    return render_template('peptide_detail.html', peptide=peptide, research=research)


@app.route('/compare')
@login_required
def compare():
    """Compare peptides side by side"""
    # Get peptide IDs from query params (e.g., ?ids=1,2,3,4)
    peptide_ids_param = request.args.get('ids', '')
    
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    # If no IDs specified, get first 4 peptides as defaults
    if peptide_ids_param:
        peptide_ids = [int(id.strip()) for id in peptide_ids_param.split(',') if id.strip().isdigit()]
        items = [db.get_peptide(pid) for pid in peptide_ids if db.get_peptide(pid)]
    else:
        # Default: show first 4 peptides
        all_peptides = db.list_peptides()
        items = all_peptides[:4] if len(all_peptides) >= 4 else all_peptides
    
    # Calculate comparison scores (heuristic for UI)
    for item in items:
        item.scores = {
            'evidence': 4 if item.research_links else 2,
            'convenience': 5 if item.primary_route and 'subcutaneous' in str(item.primary_route.value).lower() else 3,
            'cost': 3,  # Default middle score
            'complexity': 2 if item.frequency_per_day and item.frequency_per_day == 1 else 4
        }
    
    # Prepare chart data for radar comparison
    chart_labels = ['Evidence', 'Convenience', 'Cost', 'Complexity']
    chart_series = [
        {
            'label': item.name,
            'data': [
                item.scores['evidence'],
                item.scores['convenience'],
                item.scores['cost'],
                item.scores['complexity']
            ]
        }
        for item in items
    ]
    
    db_session.close()
    
    return render_template('compare.html', 
                         items=items,
                         chart_labels=chart_labels,
                         chart_series=chart_series)


@app.route('/calculator', methods=['GET', 'POST'])
@login_required
def calculator():
    """Reconstitution calculator"""
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
    
    # Get peptide list for dropdown
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    peptides = db.list_peptides()
    db_session.close()
    
    return render_template('calculator.html', result=result, peptides=peptides)


@app.route('/vials')
@login_required
def vials():
    """List vials"""
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    active_vials = db.list_active_vials()
    db_session.close()
    
    return render_template('vials.html', vials=active_vials)


@app.route('/vials/add', methods=['GET', 'POST'])
@login_required
def add_vial():
    """Add new vial"""
    if request.method == 'POST':
        try:
            peptide_id = int(request.form.get('peptide_id'))
            mg_amount = float(request.form.get('mg_amount'))
            vendor = request.form.get('vendor') or None
            lot_number = request.form.get('lot_number') or None
            
            reconstitute = request.form.get('reconstitute') == 'yes'
            
            db_session = get_session(db_url)
            db = PeptideDB(db_session)
            
            if reconstitute:
                ml_water = float(request.form.get('ml_water'))
                vial = db.add_vial(
                    peptide_id=peptide_id,
                    mg_amount=mg_amount,
                    bacteriostatic_water_ml=ml_water,
                    reconstitution_date=datetime.now(),
                    vendor=vendor,
                    lot_number=lot_number
                )
            else:
                vial = db.add_vial(
                    peptide_id=peptide_id,
                    mg_amount=mg_amount,
                    vendor=vendor,
                    lot_number=lot_number
                )
            
            db_session.close()
            flash(f'Vial added successfully! (Concentration: {vial.concentration_mcg_per_ml} mcg/ml)', 'success')
            return redirect(url_for('vials'))
            
        except (ValueError, TypeError) as e:
            flash(f'Error adding vial: {e}', 'danger')
    
    # Get peptides for dropdown
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    peptides = db.list_peptides()
    db_session.close()
    
    return render_template('add_vial.html', peptides=peptides)


@app.route('/protocols')
@login_required
def protocols():
    """List protocols"""
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    active_protocols = db.list_active_protocols()
    db_session.close()
    
    return render_template('protocols.html', protocols=active_protocols)


@app.route('/protocols/add', methods=['GET', 'POST'])
@login_required
def add_protocol():
    """Create new protocol"""
    if request.method == 'POST':
        try:
            peptide_id = int(request.form.get('peptide_id'))
            name = request.form.get('name')
            dose_mcg = float(request.form.get('dose_mcg'))
            frequency = int(request.form.get('frequency_per_day'))
            duration = int(request.form.get('duration_days'))
            goals = request.form.get('goals') or None
            
            db_session = get_session(db_url)
            db = PeptideDB(db_session)
            
            protocol = db.create_protocol(
                peptide_id=peptide_id,
                name=name,
                dose_mcg=dose_mcg,
                frequency_per_day=frequency,
                duration_days=duration,
                goals=goals,
                start_date=datetime.now()
            )
            
            db_session.close()
            flash(f'Protocol "{name}" created successfully!', 'success')
            return redirect(url_for('protocols'))
            
        except (ValueError, TypeError) as e:
            flash(f'Error creating protocol: {e}', 'danger')
    
    # Get peptides for dropdown
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    peptides = db.list_peptides()
    db_session.close()
    
    return render_template('add_protocol.html', peptides=peptides)


@app.route('/protocols/<int:protocol_id>')
@login_required
def protocol_detail(protocol_id):
    """View protocol details and history"""
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    protocol = db.get_protocol(protocol_id)
    if not protocol:
        flash('Protocol not found.', 'danger')
        return redirect(url_for('protocols'))
    
    injections = db.get_protocol_injections(protocol_id, limit=50)
    
    db_session.close()
    return render_template('protocol_detail.html', protocol=protocol, injections=injections)


@app.route('/injections/log', methods=['GET', 'POST'])
@login_required
def log_injection():
    """Log an injection"""
    if request.method == 'POST':
        try:
            protocol_id = int(request.form.get('protocol_id'))
            vial_id = int(request.form.get('vial_id'))
            dose_mcg = float(request.form.get('dose_mcg'))
            volume_ml = float(request.form.get('volume_ml'))
            site = request.form.get('injection_site') or None
            notes = request.form.get('subjective_notes') or None
            
            db_session = get_session(db_url)
            db = PeptideDB(db_session)
            
            injection = db.log_injection(
                protocol_id=protocol_id,
                vial_id=vial_id,
                dose_mcg=dose_mcg,
                volume_ml=volume_ml,
                injection_site=site,
                subjective_notes=notes
            )
            
            db_session.close()
            flash('Injection logged successfully!', 'success')
            return redirect(url_for('dashboard'))
            
        except (ValueError, TypeError) as e:
            flash(f'Error logging injection: {e}', 'danger')
    
    # Get active protocols and vials
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    protocols = db.list_active_protocols()
    vials = db.list_active_vials()
    
    db_session.close()
    
    return render_template('log_injection.html', protocols=protocols, vials=vials)


@app.route('/history')
@login_required
def history():
    """View injection history"""
    days = request.args.get('days', 30, type=int)
    
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    injections = db.get_recent_injections(days=days)
    
    db_session.close()
    
    return render_template('history.html', injections=injections, days=days)


# ==================== AI CHAT ROUTES ====================

@app.route('/chat')
@login_required
def chat():
    """AI Chat Assistant page"""
    return render_template('chat.html')


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    """Handle AI chat messages"""
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
        
        # Get user's peptide data for context
        db_session = get_session(db_url)
        db = PeptideDB(db_session)
        
        # Get user's protocols and peptides
        protocols = db.list_active_protocols()
        all_peptides = db.list_peptides()
        
        # Build context about user's data
        user_context = f"User has {len(protocols)} active protocols"
        if protocols:
            protocol_list = ", ".join([f"{p.peptide.name} ({p.dose_mcg}mcg {p.frequency_per_day}x/day)" for p in protocols[:3]])
            user_context += f": {protocol_list}"
        
        db_session.close()
        
        # System prompt with peptide knowledge
        system_prompt = f"""You are an expert peptide advisor for a peptide tracking application. You help users understand peptides, create protocols, and manage their peptide regimens safely.

IMPORTANT SAFETY GUIDELINES:
- Always emphasize that this is educational information only
- Recommend users consult healthcare professionals before starting any peptide
- Never diagnose conditions or prescribe treatments
- Be conservative with dosing recommendations
- Warn about potential side effects and contraindications

AVAILABLE PEPTIDES IN DATABASE:
{', '.join([p.name for p in all_peptides[:20]])}

USER'S CURRENT DATA:
{user_context}

When answering:
1. Be helpful and informative
2. Provide specific dosing ranges when appropriate
3. Explain benefits and risks
4. Suggest peptide stacks when relevant
5. Reference the user's current protocols when helpful
6. Keep responses concise but complete (2-4 paragraphs max)

Remember: You're a knowledgeable assistant, not a doctor."""

        # Call OpenAI API (new v1.0+ syntax)
        from openai import OpenAI
        client = OpenAI(api_key=Config.OPENAI_API_KEY)
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=500,
            temperature=0.7
        )
        
        assistant_message = response.choices[0].message.content
        
        return jsonify({
            'message': assistant_message,
            'success': True
        })
        
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({
            'error': 'Failed to get AI response. Please try again.',
            'success': False
        }), 500


# ==================== ERROR HANDLERS ====================

@app.route('/api/vials/<int:peptide_id>')
@login_required
def api_vials_by_peptide(peptide_id):
    """Get active vials for a peptide (AJAX endpoint)"""
    db_session = get_session(db_url)
    db = PeptideDB(db_session)
    
    vials = db.list_active_vials(peptide_id)
    
    vials_data = [{
        'id': v.id,
        'mg_amount': v.mg_amount,
        'concentration': v.concentration_mcg_per_ml,
        'remaining_ml': v.remaining_ml
    } for v in vials]
    
    db_session.close()
    
    return jsonify(vials_data)




# ==================== RECOMMENDATIONS API ====================

@app.route('/api/recommendations')
@login_required
def api_recommendations():
    """
    Return a simple, explainable recommendation list based on:
    - Age (heuristic buckets)
    - Selected goals (keywords)
    - Peptide text fields (notes/benefits/common_name/name)
    This is a UI prioritization tool only — not medical advice.
    """
    age = request.args.get('age', 35, type=int)
    goals_raw = request.args.get('goals', '', type=str)
    goals = [g.strip().lower() for g in goals_raw.split(',') if g.strip()]

    # Keyword maps (tunable)
    goal_keywords = {
        'fat loss': ['fat', 'weight', 'glp', 'metabolic', 'insulin', 'appetite'],
        'recovery': ['recovery', 'injury', 'tendon', 'joint', 'healing', 'repair'],
        'skin': ['skin', 'collagen', 'wrinkle', 'elastic', 'hair'],
        'cognition': ['cognition', 'focus', 'memory', 'brain', 'neuro', 'mood'],
        'longevity': ['longevity', 'mitochond', 'aging', 'senescence', 'energy', 'oxidative'],
    }

    # Age weighting (very rough)
    age_bias = []
    if age >= 55:
        age_bias = ['longevity', 'recovery']
    elif age >= 40:
        age_bias = ['recovery', 'skin', 'longevity']
    else:
        age_bias = ['recovery', 'cognition']

    # Combine explicit goals with bias
    goal_order = []
    for g in goals + age_bias:
        if g and g not in goal_order:
            goal_order.append(g)

    db_session = get_session(db_url)
    try:
        # Import Peptide from models already at top
        peptides = db_session.query(Peptide).all()

        items = []
        for p in peptides:
            # Build searchable text
            fields = []
            for attr in ('name', 'common_name', 'notes', 'benefits', 'mechanism', 'category'):
                v = getattr(p, attr, None)
                if v:
                    fields.append(str(v))
            hay = " ".join(fields).lower()

            score = 0.0
            matched = []

            # Base score for having any descriptive text
            if len(hay) > 20:
                score += 5

            # Goal matches
            for g in goal_order:
                kw = goal_keywords.get(g, [])
                hits = sum(1 for k in kw if k in hay)
                if hits:
                    score += 12 + hits * 2
                    matched.append(g)

            # Slight preference for common peptide names matching goal intent
            pname = (getattr(p, 'name', '') or '').lower()
            if 'retatrutide' in pname and ('fat loss' in goal_order):
                score += 10
            if 'bpc' in pname and ('recovery' in goal_order):
                score += 8
            if 'tb-500' in pname and ('recovery' in goal_order):
                score += 6
            if 'ghk' in pname and ('skin' in goal_order):
                score += 8
            if 'ss-31' in pname and ('longevity' in goal_order):
                score += 7
            if 'mots' in pname and ('longevity' in goal_order or 'fat loss' in goal_order):
                score += 6

            # Format image url if present
            img_fn = getattr(p, 'image_filename', None)
            img_url = url_for('static', filename=f'img/{img_fn}') if img_fn else None

            reason = " + ".join([g.title() for g in matched[:3]]) if matched else "Based on age bucket + peptide notes/benefits text"

            items.append({
                "id": getattr(p, 'id', None),
                "name": getattr(p, 'name', 'Unknown'),
                "common_name": getattr(p, 'common_name', None),
                "category": getattr(p, 'category', None) or "General",
                "score": score,
                "reason": reason,
                "goals_matched": [g.title() for g in matched[:5]],
                "image_url": img_url,
            })

        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        # Filter out rows without an id (shouldn't happen, but defensive)
        items = [it for it in items if it.get("id") is not None][:10]

        return jsonify({
            "age": age,
            "goals": [g.title() for g in goals],
            "items": items,
        })
    finally:
        db_session.close()



# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def server_error(error):
    return render_template('500.html'), 500


# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    # Create tables
    engine = create_engine(db_url)
    ModelBase.metadata.create_all(engine)
    
    print("\n" + "="*60)
    print("PEPTIDE TRACKER WEB APP")
    print("="*60)
    print(f"Database: {db_url}")
    print("Starting server at: http://127.0.0.1:5000")
    print("Press CTRL+C to stop")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
