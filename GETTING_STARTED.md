# PEPTIDE TRACKER - GETTING STARTED GUIDE

## Quick Start (5 Minutes)

### Step 1: Install Python Dependencies
```bash
cd peptide_app
pip install -r requirements.txt
```

### Step 2: Initialize Database
```bash
python seed_data.py
```
This creates a SQLite database with 10+ common peptides pre-loaded.

### Step 3: Try the Calculator
```bash
python calculator.py
```
Follow the prompts to calculate reconstitution for any peptide.

### Step 4: Run the CLI
```bash
python cli.py
```
Interactive menu to manage peptides, vials, protocols, and injections.

---

## What You Just Built

### 📊 Complete Database Schema
- **Peptides**: Master database of peptide information
- **Vials**: Track individual vials with reconstitution dates
- **Protocols**: Define dosing schedules and cycles
- **Injections**: Log each injection with notes
- **Research**: Store studies and research notes

### 🧮 Reconstitution Calculator
Automatically calculates:
- Concentration (mcg/ml)
- Dose volume (ml)
- Syringe units
- Total doses per vial
- How long vial will last

### 💾 Flexible Storage
- **SQLite**: No setup, single file database (default)
- **PostgreSQL**: Production-ready, multi-device sync
- Easy to switch between them

### 🤖 AI-Ready Architecture
Built for future integration with:
- Claude/OpenAI APIs for natural language queries
- pgvector for semantic search
- RAG for intelligent research assistance
- LangChain for advanced workflows

---

## Project Files Explained

### Core Application
- **models.py** - SQLAlchemy database models (Peptide, Vial, Protocol, Injection)
- **database.py** - CRUD operations and business logic
- **calculator.py** - Reconstitution and dosing calculations
- **config.py** - Configuration and environment variables

### Utilities
- **seed_data.py** - Populate database with 10+ common peptides
- **cli.py** - Interactive command-line interface
- **example.py** - Code examples and demonstrations
- **setup.py** - Quick setup script

### Configuration
- **requirements.txt** - Python dependencies
- **.env.example** - Template for environment variables
- **.gitignore** - Ignore database files and secrets

### Documentation
- **README.md** - Full documentation
- **GETTING_STARTED.md** - This file

---

## Example Workflow

Here's a typical workflow using the Peptide Tracker:

### 1. You receive a new vial of BPC-157 (5mg)

**Option A: Use CLI**
```bash
python cli.py
# Select: 4. Add vial
# Enter: BPC-157, 5mg, vendor info
```

**Option B: Use Python**
```python
from models import get_session
from database import PeptideDB

session = get_session("sqlite:///peptide_tracker.db")
db = PeptideDB(session)

bpc = db.get_peptide_by_name("BPC-157")
vial = db.add_vial(
    peptide_id=bpc.id,
    mg_amount=5,
    vendor="PeptideSciences"
)
```

### 2. Calculate how to reconstitute it

**Use the calculator:**
```bash
python calculator.py
# Peptide: BPC-157
# Vial size: 5 mg
# Water: 2 ml
# Dose: 250 mcg
# Frequency: 2x/day

# Output:
# Concentration: 2500 mcg/ml
# Dose volume: 0.1 ml (10 units)
# Vial lasts: 10 days
```

### 3. Reconstitute the vial and update database

```bash
python cli.py
# Select: 4. Add vial (or update existing)
# Reconstitute: Yes
# Water added: 2 ml
```

### 4. Create a protocol

```bash
python cli.py
# Select: 5. Create protocol
# Name: "Shoulder Injury Recovery"
# Dose: 250 mcg
# Frequency: 2x/day
# Duration: 30 days
```

### 5. Log your injections

```bash
python cli.py
# Select: 6. Log injection
# Select your protocol and vial
# Site: "shoulder"
# Notes: "No side effects"
```

### 6. Track your progress

```bash
python cli.py
# Select: 8. View recent injections
# Shows all injections with dates, doses, notes
```

---

## Pre-Loaded Peptides

The database includes these peptides with full details:

1. **BPC-157** - Healing and recovery (200-500 mcg, 2x/day)
2. **TB-500** - Tissue repair (2000-5000 mcg, 1x/day)
3. **GHK-Cu** - Anti-aging (1000-3000 mcg, 1x/day)
4. **Ipamorelin** - GH secretagogue (200-300 mcg, 2x/day)
5. **CJC-1295** - Long-acting GHRH (500-1000 mcg, 1x/week)
6. **Melanotan II** - Tanning/libido (250-1000 mcg, 1x/day)
7. **Semax** - Cognitive enhancement (300-600 mcg, 2x/day)
8. **Selank** - Anxiety reduction (250-500 mcg, 2x/day)
9. **Epitalon** - Telomere support (5000-10000 mcg, 1x/day)
10. **Tesamorelin** - Fat reduction (1000-2000 mcg, 1x/day)

Each includes:
- Molecular weight
- Dosage ranges
- Half-life
- Administration route
- Storage requirements
- Benefits
- Contraindications
- Research links

---

## Adding Your Own Peptides

```python
from models import get_session, AdministrationRoute, StorageMethod
from database import PeptideDB

session = get_session("sqlite:///peptide_tracker.db")
db = PeptideDB(session)

# Add custom peptide
my_peptide = db.add_peptide(
    name="Custom Peptide",
    common_name="My Peptide",
    molecular_weight=1234.56,
    typical_dose_min=100,
    typical_dose_max=500,
    frequency_per_day=2,
    half_life_hours=6,
    primary_route=AdministrationRoute.SUBCUTANEOUS,
    storage_method=StorageMethod.REFRIGERATOR,
    shelf_life_days=30,
    primary_benefits="List benefits here",
    notes="Additional information"
)

print(f"Added peptide: {my_peptide.name}")
session.close()
```

---

## Database Location

When using SQLite (default):
- **Location**: `peptide_tracker.db` in the same folder as the scripts
- **Backup**: Just copy this file
- **Portable**: Move the file anywhere
- **View**: Use any SQLite browser (DB Browser for SQLite, etc.)

When using PostgreSQL:
- **Location**: PostgreSQL server
- **Backup**: Use `pg_dump`
- **Multi-device**: Access from anywhere
- **Production**: Better for web apps

---

## Next Steps

### Immediate Use
1. ✅ Run `python seed_data.py` to initialize
2. ✅ Try `python calculator.py` for reconstitution
3. ✅ Use `python cli.py` for daily management
4. ✅ Review `python example.py` for API usage

### Customization
- Add your own peptides to the database
- Customize dosing ranges for your protocols
- Add research notes and studies
- Track multiple cycles and compare results

### Future Enhancements
- **Web Interface**: Build Flask app (skeleton ready)
- **AI Integration**: Add Claude API for natural language queries
- **Vector Search**: Enable semantic search with pgvector
- **Mobile Access**: Deploy PostgreSQL backend
- **Data Visualization**: Add matplotlib/plotly charts
- **Export Reports**: Generate PDF protocol summaries

---

## Troubleshooting

**Q: "No module named 'sqlalchemy'"**
A: Run `pip install -r requirements.txt`

**Q: "Database not found"**
A: Run `python seed_data.py` first

**Q: "I want to use PostgreSQL instead of SQLite"**
A: 
1. Install PostgreSQL
2. Create database
3. Update `.env` file
4. In `seed_data.py`, change `use_sqlite=False`
5. Run `python seed_data.py`

**Q: "How do I reset the database?"**
A: Delete `peptide_tracker.db` and run `python seed_data.py` again

**Q: "Can I add more peptides?"**
A: Yes! See "Adding Your Own Peptides" section above

---

## Safety Reminders

⚠️ **Important Disclaimers:**
- This is an organizational tool, not medical advice
- Consult healthcare professionals before using peptides
- Many peptides are research chemicals
- Always source from reputable vendors
- Test for purity and authenticity
- Understand local regulations

---

## Support Resources

- **README.md** - Full documentation
- **example.py** - Working code examples
- **Code comments** - Detailed explanations
- **SQLAlchemy docs** - Database operations
- **PubMed** - Peptide research

---

**Version**: 1.0.0  
**Author**: Yoni (Built with Claude)  
**License**: MIT - Free to use and modify  
**Status**: Ready for personal use

---

## Want to Contribute?

This is an open-source project. Feel free to:
- Add more peptides to seed_data.py
- Improve the calculator
- Build a web interface
- Add data visualization
- Integrate AI features
- Share your improvements

Happy tracking! 🧬💉📊
