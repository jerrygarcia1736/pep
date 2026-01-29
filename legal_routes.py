# ADD THESE ROUTES TO YOUR app.py

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
    return render_if_exists("user_agreement.html", fallback_endpoint="dashboard")


@app.route("/accept-agreement", methods=["POST"])
@login_required
def accept_agreement():
    """Process user agreement acceptance"""
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


# Add agreement check to login_required decorator
# Modify your existing login_required decorator:

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in.", "warning")
            return redirect(url_for("login"))
        
        # Check if user has accepted agreement
        db = get_session(db_url)
        try:
            user = db.query(User).filter_by(id=session["user_id"]).first()
            if user and not user.agreement_accepted_at:
                # User hasn't accepted agreement yet
                return redirect(url_for("user_agreement"))
        finally:
            db.close()
        
        return f(*args, **kwargs)
    return wrapper


# Add this column to your User model:
# agreement_accepted_at = Column(DateTime, nullable=True)  # Null = not accepted yet
