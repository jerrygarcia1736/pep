# RUNNING THE WEB APP - QUICK START

## Step 1: Install New Dependencies

You need to install Flask (web framework):

```bash
pip install flask werkzeug
```

Or install everything from updated requirements:
```bash
pip install -r requirements.txt
```

## Step 2: Make Sure Database is Set Up

If you haven't already run the seed script:
```bash
python seed_data.py
```

This creates `peptide_tracker.db` with 10+ peptides loaded.

## Step 3: Run the Web App

```bash
python app.py
```

You should see:
```
============================================================
PEPTIDE TRACKER WEB APP
============================================================
Database: sqlite:///peptide_tracker.db
Starting server at: http://127.0.0.1:5000
Press CTRL+C to stop
============================================================
```

## Step 4: Open Your Browser

Go to: **http://127.0.0.1:5000**

Or: **http://localhost:5000**

## Step 5: Create an Account

1. Click "Register"
2. Create username, email, password
3. Click "Create Account"
4. Login with your new credentials

## Step 6: Start Using the App!

- **Dashboard** - See your stats and quick actions
- **Peptides** - Browse the peptide library
- **Calculator** - Calculate reconstitution
- **Vials** - Track your vial inventory
- **Protocols** - Create and manage dosing protocols
- **Log Injection** - Record each injection
- **History** - View all your injection logs

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'flask'"
Run: `pip install flask`

### "Address already in use"
Another app is using port 5000. Either:
- Stop the other app
- Change port in app.py: `app.run(port=5001)`

### Can't create account / database errors
Make sure the database exists:
```bash
python seed_data.py
```

### Want to access from phone/tablet on same network
Change app.py last line to:
```python
app.run(debug=True, host='0.0.0.0', port=5000)
```
Then access via your computer's IP: `http://192.168.1.X:5000`

---

## What's Next?

### Local Testing (Now)
✅ Run on your computer
✅ Create accounts and test features
✅ Share with friends on your network

### Deploy to Internet (Free!)
1. Create free account on Render.com
2. Connect your GitHub repo
3. Deploy with one click
4. Access from anywhere!

### Add Features
- Payment integration (Stripe)
- AI assistant (Claude API)
- Email notifications
- Data export
- Mobile app wrapper

---

## File Structure

```
peptide_app/
├── app.py                  # Main Flask application
├── models.py               # Database models
├── database.py             # Database operations  
├── calculator.py           # Reconstitution calculator
├── config.py              # Configuration
├── templates/             # HTML templates
│   ├── base.html          # Base template
│   ├── index.html         # Landing page
│   ├── login.html         # Login page
│   ├── register.html      # Registration
│   ├── dashboard.html     # Main dashboard
│   ├── calculator.html    # Calculator page
│   ├── peptides.html      # Peptide library
│   └── log_injection.html # Injection logging
├── static/
│   ├── css/
│   │   └── style.css      # Custom styles
│   └── js/
│       └── app.js         # JavaScript
└── peptide_tracker.db     # SQLite database
```

---

## Security Notes

⚠️ **This is a development server - DO NOT use in production!**

For production deployment:
- Use proper WSGI server (Gunicorn)
- Set strong SECRET_KEY
- Use HTTPS
- Enable CSRF protection
- Implement rate limiting
- Regular backups

---

**Need help? Check README.md or GETTING_STARTED.md**
