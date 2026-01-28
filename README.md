# Peptide Tracker

A comprehensive Python application for managing peptide protocols, tracking injections, and calculating reconstitution dosages. Built with PostgreSQL/SQLite and designed for easy AI integration.

## Features

### Current Features
- **Peptide Database**: Pre-loaded with 10+ common peptides (BPC-157, TB-500, GHK-Cu, etc.)
- **Reconstitution Calculator**: Calculate concentrations, dosages, and syringe units
- **Vial Management**: Track vials, reconstitution dates, and remaining volume
- **Protocol Creation**: Define and manage dosing protocols
- **Injection Logging**: Track each injection with timestamps, sites, and notes
- **Research Notes**: Store and organize peptide research and studies

### Planned Features
- 🤖 **AI Integration**: Natural language queries using Claude/OpenAI APIs
- 🔍 **Vector Search**: Semantic search through research notes using pgvector
- 📊 **Data Visualization**: Progress tracking and protocol analysis
- 🌐 **Web Interface**: Flask-based web UI for easier access
- 📱 **Multi-device Sync**: PostgreSQL backend for cross-device access

## Tech Stack

- **Database**: PostgreSQL (or SQLite for local use)
- **ORM**: SQLAlchemy 2.0+
- **Python**: 3.8+
- **Future**: Flask, pgvector, OpenAI/Anthropic APIs, LangChain

## Installation

### Prerequisites
- Python 3.8 or higher
- PostgreSQL (optional - can use SQLite)

### Quick Start

1. **Clone/Download the project**
```bash
cd peptide_app
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Setup database configuration**
```bash
# Copy example env file
cp .env.example .env

# Edit .env with your database settings (or use SQLite default)
```

5. **Initialize database and seed with common peptides**
```bash
# This will create tables and add 10+ common peptides
python seed_data.py
```

6. **Run the CLI**
```bash
python cli.py
```

## Database Setup

### Option 1: SQLite (Easiest - No Setup Required)
The app is configured to use SQLite by default in the seed script and CLI. No additional setup needed!

### Option 2: PostgreSQL (Recommended for AI Features)

1. **Install PostgreSQL**
```bash
# macOS
brew install postgresql@15
brew services start postgresql@15

# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql

# Windows: Download from postgresql.org
```

2. **Create database**
```bash
psql postgres
CREATE DATABASE peptide_tracker;
CREATE USER peptide_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE peptide_tracker TO peptide_user;
\q
```

3. **Update .env file**
```
DB_NAME=peptide_tracker
DB_USER=peptide_user
DB_PASSWORD=your_password
```

4. **Run seed script**
```bash
# Edit seed_data.py, set use_sqlite=False
python seed_data.py
```

## Usage Examples

### Using the CLI

```bash
python cli.py
```

The CLI provides:
1. List all peptides
2. View peptide details
3. Calculate reconstitution
4. Add vial
5. Create protocol
6. Log injection
7. View active protocols
8. View recent injections

### Using the Calculator Directly

```bash
python calculator.py
```

Interactive calculator that walks you through:
- Vial size (mg)
- Water volume (ml)
- Desired dose (mcg)
- Frequency per day

### Python API Examples

```python
from models import get_session
from database import PeptideDB
from calculator import PeptideCalculator

# Get database session
session = get_session("sqlite:///peptide_tracker.db")
db = PeptideDB(session)

# Get a peptide
bpc = db.get_peptide_by_name("BPC-157")
print(f"Typical dose: {bpc.typical_dose_min}-{bpc.typical_dose_max} mcg")

# Calculate reconstitution
report = PeptideCalculator.full_reconstitution_report(
    peptide_name="BPC-157",
    mg_peptide=5,      # 5mg vial
    ml_water=2,        # 2ml BAC water
    desired_dose_mcg=250,  # 250mcg per injection
    doses_per_day=2    # 2x daily
)
PeptideCalculator.print_reconstitution_report(report)

# Add a vial
vial = db.add_vial(
    peptide_id=bpc.id,
    mg_amount=5,
    bacteriostatic_water_ml=2,
    vendor="PeptideSciences",
    reconstitution_date=datetime.now()
)

# Create a protocol
protocol = db.create_protocol(
    peptide_id=bpc.id,
    name="BPC-157 Shoulder Injury Recovery",
    dose_mcg=250,
    frequency_per_day=2,
    duration_days=30,
    goals="Heal rotator cuff strain"
)

# Log an injection
injection = db.log_injection(
    protocol_id=protocol.id,
    vial_id=vial.id,
    dose_mcg=250,
    volume_ml=0.25,
    injection_site="shoulder",
    subjective_notes="No side effects, slight warmth at injection site"
)

# Get recent injections
recent = db.get_recent_injections(days=7)
for inj in recent:
    print(f"{inj.timestamp}: {inj.dose_mcg}mcg - {inj.subjective_notes}")

session.close()
```

## Project Structure

```
peptide_app/
├── models.py           # SQLAlchemy database models
├── database.py         # CRUD operations and business logic
├── calculator.py       # Reconstitution and dosing calculations
├── config.py          # Configuration and environment variables
├── seed_data.py       # Initialize DB with common peptides
├── cli.py             # Command-line interface
├── requirements.txt   # Python dependencies
├── .env.example       # Environment variable template
└── README.md          # This file
```

## Common Peptides Included

The database is pre-seeded with:
- **BPC-157** - Healing and recovery
- **TB-500** - Tissue repair and flexibility
- **GHK-Cu** - Anti-aging and skin health
- **Ipamorelin** - GH secretagogue
- **CJC-1295** - Long-acting GHRH
- **Melanotan II** - Tanning and libido
- **Semax** - Cognitive enhancement
- **Selank** - Anxiety reduction
- **Epitalon** - Telomere support
- **Tesamorelin** - Visceral fat reduction

Each includes:
- Molecular weight
- Typical dosage ranges
- Half-life information
- Administration routes
- Storage requirements
- Primary benefits
- Contraindications
- Research links

## Future AI Integration

The architecture is designed for easy AI integration:

### Natural Language Interface
```python
# Future capability
query = "What's my BPC-157 protocol and when did I last inject?"
# AI would understand context and retrieve relevant data
```

### Research Assistant
```python
# Future capability
question = "What peptides might help with joint recovery?"
# RAG system would search your research notes + external sources
```

### Smart Recommendations
```python
# Future capability
# AI analyzes your logs and suggests:
# - Optimal dosing times based on half-life
# - Potential peptide combinations
# - Protocol adjustments based on progress notes
```

## Contributing

This is an open-source personal project. Feel free to fork and customize for your needs.

## Disclaimer

**This tool is for informational and organizational purposes only.**

- Not medical advice
- Consult healthcare professionals before using any peptides
- Many peptides are research chemicals with limited human studies
- Peptide use may be regulated in your jurisdiction
- Always source from reputable vendors and test for purity

## License

MIT License - Use freely, but at your own risk.

## Support

For issues or questions, consult:
- Documentation in this README
- Code comments in source files
- SQLAlchemy documentation for database questions
- Peptide research via PubMed and peer-reviewed sources

---

**Version**: 1.0.0  
**Last Updated**: January 2026  
**Status**: Active Development
