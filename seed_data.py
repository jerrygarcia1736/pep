"""
Seed Database with Common Peptides
Populate database with well-known peptides and their properties
"""

from datetime import datetime
from models import get_session, AdministrationRoute, StorageMethod
from database import PeptideDB
from config import Config


def seed_common_peptides(session):
    """Add common peptides to the database"""
    db = PeptideDB(session)
    
    peptides_data = [
        {
            "name": "BPC-157",
            "common_name": "Body Protection Compound-157",
            "molecular_weight": 1419.55,
            "typical_dose_min": 200,
            "typical_dose_max": 500,
            "frequency_per_day": 2,
            "half_life_hours": 4,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Accelerated healing of muscles, tendons, ligaments; gut health; anti-inflammatory",
            "contraindications": "Limited human studies; consult healthcare provider",
            "notes": "Pentadecapeptide with systemic healing properties. Often used for injury recovery.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/31633635/"
        },
        {
            "name": "TB-500",
            "common_name": "Thymosin Beta-4",
            "molecular_weight": 4963.44,
            "typical_dose_min": 2000,
            "typical_dose_max": 5000,
            "frequency_per_day": 1,
            "half_life_hours": 24,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Promotes healing, reduces inflammation, improves flexibility",
            "contraindications": "Not for use with active cancer; limited human studies",
            "notes": "Often stacked with BPC-157 for injury recovery. Loading phase often used.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/27479156/"
        },
        {
            "name": "GHK-Cu",
            "common_name": "Copper Peptide",
            "molecular_weight": 340.38,
            "typical_dose_min": 1000,
            "typical_dose_max": 3000,
            "frequency_per_day": 1,
            "half_life_hours": 24,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Anti-aging, skin health, wound healing, hair growth, tissue remodeling",
            "contraindications": "Avoid with copper sensitivity",
            "notes": "Natural tripeptide that decreases with age. Also available in topical form.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/22935136/"
        },
        {
            "name": "Ipamorelin",
            "common_name": "Growth Hormone Secretagogue",
            "molecular_weight": 711.85,
            "typical_dose_min": 200,
            "typical_dose_max": 300,
            "frequency_per_day": 2,
            "half_life_hours": 2,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Stimulates GH release, improved recovery, better sleep, fat loss",
            "contraindications": "Not for use during pregnancy; consult endocrinologist",
            "notes": "Often combined with CJC-1295. Take on empty stomach for best results.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/9849822/"
        },
        {
            "name": "CJC-1295",
            "common_name": "Growth Hormone Releasing Hormone",
            "molecular_weight": 3647.28,
            "typical_dose_min": 500,
            "typical_dose_max": 1000,
            "frequency_per_day": 1,
            "half_life_hours": 168,  # ~7 days
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Sustained GH elevation, muscle growth, fat loss, improved recovery",
            "contraindications": "Monitor for insulin resistance; consult healthcare provider",
            "notes": "DAC version has long half-life. Often paired with Ipamorelin or GHRP-6.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/16352683/"
        },
        {
            "name": "Melanotan II",
            "common_name": "MT-2",
            "molecular_weight": 1024.18,
            "typical_dose_min": 250,
            "typical_dose_max": 1000,
            "frequency_per_day": 1,
            "half_life_hours": 6,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Tanning, libido enhancement, appetite suppression",
            "contraindications": "Can cause nausea, flushing; start with low dose",
            "notes": "Loading phase recommended. Effects include darkening of moles/freckles.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/8932311/"
        },
        {
            "name": "Semax",
            "common_name": "Heptapeptide ACTH(4-10)",
            "molecular_weight": 813.93,
            "typical_dose_min": 300,
            "typical_dose_max": 600,
            "frequency_per_day": 2,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.NASAL,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Cognitive enhancement, neuroprotection, focus, mood",
            "contraindications": "Limited long-term human studies",
            "notes": "Developed in Russia. Often used nasally. Start with lower concentration.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/12408051/"
        },
        {
            "name": "Selank",
            "common_name": "Anxiolytic Peptide",
            "molecular_weight": 751.89,
            "typical_dose_min": 250,
            "typical_dose_max": 500,
            "frequency_per_day": 2,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.NASAL,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Anxiety reduction, immune modulation, cognitive function",
            "contraindications": "Limited long-term human studies",
            "notes": "Similar structure to Semax. Used for anxiety and immune support.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/19234797/"
        },
        {
            "name": "Epitalon",
            "common_name": "Epithalamin",
            "molecular_weight": 390.35,
            "typical_dose_min": 5000,
            "typical_dose_max": 10000,
            "frequency_per_day": 1,
            "half_life_hours": 6,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Telomere lengthening, anti-aging, circadian rhythm regulation",
            "contraindications": "Limited human clinical data",
            "notes": "Typically cycled (10-20 day cycles). Anti-aging properties being researched.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/12490989/"
        },
        {
            "name": "Tesamorelin",
            "common_name": "Growth Hormone Releasing Factor",
            "molecular_weight": 5135.89,
            "typical_dose_min": 1000,
            "typical_dose_max": 2000,
            "frequency_per_day": 1,
            "half_life_hours": 0.5,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Visceral fat reduction, improved lipid profile",
            "contraindications": "FDA approved for HIV lipodystrophy; prescription required",
            "notes": "Short half-life. FDA-approved peptide. Targets visceral adipose tissue.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/20664028/"
        }
    ]
    
    print("\n" + "="*60)
    print("SEEDING DATABASE WITH COMMON PEPTIDES")
    print("="*60 + "\n")
    
    for peptide_data in peptides_data:
        try:
            peptide = db.add_peptide(**peptide_data)
            print(f"✓ Added: {peptide.name} ({peptide.common_name})")
        except Exception as e:
            print(f"✗ Error adding {peptide_data['name']}: {e}")
    
    print(f"\n{'='*60}")
    print(f"Seeded {len(peptides_data)} peptides successfully!")
    print("="*60 + "\n")


def main():
    """Run seeding script"""
    # You can switch to SQLite for easier setup
    use_sqlite = True  # Change to False to use PostgreSQL
    
    if use_sqlite:
        db_url = "sqlite:///peptide_tracker.db"
        print("Using SQLite database for easier setup...")
    else:
        db_url = Config.DATABASE_URL
        print(f"Using PostgreSQL: {db_url}")
    
    # Create tables if they don't exist
    from models import create_database
    create_database(db_url)
    
    # Get session and seed data
    session = get_session(db_url)
    seed_common_peptides(session)
    session.close()


if __name__ == "__main__":
    main()
