"""
Add New Peptides to Database
Run this script to add 35+ additional peptides
"""

from datetime import datetime
from models import get_session, AdministrationRoute, StorageMethod
from database import PeptideDB
from config import Config

def add_new_peptides():
    """Add comprehensive peptide list"""
    
    # Use SQLite database
    session = get_session("sqlite:///peptide_tracker.db")
    db = PeptideDB(session)
    
    new_peptides = [
        # Weight Loss GLP-1 Agonists
        {
            "name": "Semaglutide",
            "common_name": "Ozempic/Wegovy",
            "molecular_weight": 4113.58,
            "typical_dose_min": 250,
            "typical_dose_max": 2400,
            "frequency_per_day": 1,
            "half_life_hours": 168,  # Once weekly
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 56,
            "primary_benefits": "Weight loss, appetite suppression, blood sugar control, cardiovascular benefits",
            "contraindications": "History of medullary thyroid carcinoma, MEN2; monitor for pancreatitis",
            "notes": "FDA-approved GLP-1 agonist. Start low and titrate up. Weekly dosing.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/34706925/"
        },
        {
            "name": "Tirzepatide",
            "common_name": "Mounjaro/Zepbound",
            "molecular_weight": 4813.0,
            "typical_dose_min": 2500,
            "typical_dose_max": 15000,
            "frequency_per_day": 1,
            "half_life_hours": 120,  # Weekly
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 28,
            "primary_benefits": "Superior weight loss, GIP/GLP-1 dual agonist, metabolic health",
            "contraindications": "Similar to semaglutide; thyroid concerns",
            "notes": "Dual incretin agonist. More effective than semaglutide for weight loss.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/35658024/"
        },
        {
            "name": "Retatrutide",
            "common_name": "Triple Agonist",
            "molecular_weight": 5300.0,
            "typical_dose_min": 4000,
            "typical_dose_max": 12000,
            "frequency_per_day": 1,
            "half_life_hours": 168,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 28,
            "primary_benefits": "Extreme weight loss, GIP/GLP-1/Glucagon triple agonist",
            "contraindications": "Investigational; similar warnings to other GLP-1 agonists",
            "notes": "Triple incretin agonist. Strongest weight loss effect. Still in trials.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/36472361/"
        },
        
        # Mitochondrial & Longevity
        {
            "name": "SS-31",
            "common_name": "Elamipretide",
            "molecular_weight": 640.0,
            "typical_dose_min": 5,
            "typical_dose_max": 40,
            "frequency_per_day": 1,
            "half_life_hours": 4,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Mitochondrial health, cardioprotection, energy production, anti-aging",
            "contraindications": "Research peptide; limited human data",
            "notes": "Cardiolipin-targeting peptide. Improves mitochondrial function.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/28286094/"
        },
        {
            "name": "MOTS-c",
            "common_name": "Mitochondrial ORF",
            "molecular_weight": 1675.0,
            "typical_dose_min": 5000,
            "typical_dose_max": 15000,
            "frequency_per_day": 1,
            "half_life_hours": 24,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Metabolism boost, exercise mimetic, longevity, insulin sensitivity",
            "contraindications": "Limited human studies",
            "notes": "Mitochondrial-derived peptide. Enhances metabolic function.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/31068470/"
        },
        {
            "name": "Humanin",
            "common_name": "HN",
            "molecular_weight": 2687.0,
            "typical_dose_min": 1000,
            "typical_dose_max": 5000,
            "frequency_per_day": 1,
            "half_life_hours": 12,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Neuroprotection, longevity, metabolic health, mitochondrial function",
            "contraindications": "Research peptide",
            "notes": "Mitochondrial-derived peptide with anti-aging properties.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/26877264/"
        },
        
        # NAD+ Precursor
        {
            "name": "NAD+",
            "common_name": "Nicotinamide Adenine Dinucleotide",
            "molecular_weight": 663.43,
            "typical_dose_min": 50,
            "typical_dose_max": 500,
            "frequency_per_day": 1,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Cellular energy, DNA repair, anti-aging, cognitive function",
            "contraindications": "Can cause flushing; start with lower doses",
            "notes": "Essential coenzyme for cellular metabolism. IM/SubQ preferred over IV.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/29514064/"
        },
        
        # Cognitive Enhancement
        {
            "name": "Cerebrolysin",
            "common_name": "Porcine Brain Peptides",
            "molecular_weight": None,
            "typical_dose_min": 5000,
            "typical_dose_max": 30000,
            "frequency_per_day": 1,
            "half_life_hours": 8,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 365,
            "primary_benefits": "Neuroprotection, neurogenesis, cognitive enhancement, stroke recovery",
            "contraindications": "Epilepsy, renal impairment",
            "notes": "Pharmaceutical-grade neurotrophic peptides. Common in Eastern Europe.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/30927944/"
        },
        {
            "name": "Dihexa",
            "common_name": "PNB-0408",
            "molecular_weight": 425.0,
            "typical_dose_min": 0.5,
            "typical_dose_max": 5,
            "frequency_per_day": 1,
            "half_life_hours": 24,
            "primary_route": AdministrationRoute.ORAL,
            "storage_method": StorageMethod.ROOM_TEMP,
            "shelf_life_days": 365,
            "primary_benefits": "Powerful cognitive enhancer, neurogenesis, memory improvement",
            "contraindications": "Very potent; research chemical; use cautiously",
            "notes": "One of the most potent cognitive enhancers. Start very low dose.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/23978516/"
        },
        {
            "name": "P21",
            "common_name": "Cerebrolysin Fragment",
            "molecular_weight": 2487.0,
            "typical_dose_min": 5000,
            "typical_dose_max": 20000,
            "frequency_per_day": 1,
            "half_life_hours": 12,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Neurogenesis, neuroprotection, cognitive enhancement",
            "contraindications": "Limited human data",
            "notes": "Derived from Cerebrolysin. Promotes BDNF.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/24412634/"
        },
        {
            "name": "NSI-189",
            "common_name": "Neurogenesis Stimulator",
            "molecular_weight": 366.0,
            "typical_dose_min": 40000,
            "typical_dose_max": 80000,
            "frequency_per_day": 1,
            "half_life_hours": 6,
            "primary_route": AdministrationRoute.ORAL,
            "storage_method": StorageMethod.ROOM_TEMP,
            "shelf_life_days": 365,
            "primary_benefits": "Hippocampal neurogenesis, depression treatment, cognitive enhancement",
            "contraindications": "Failed Phase 2 trials; research use only",
            "notes": "Stimulates hippocampal neurogenesis. Typically taken orally.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/28942748/"
        },
        
        # Sleep
        {
            "name": "DSIP",
            "common_name": "Delta Sleep-Inducing Peptide",
            "molecular_weight": 849.0,
            "typical_dose_min": 100,
            "typical_dose_max": 500,
            "frequency_per_day": 1,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Sleep quality, stress reduction, pain relief",
            "contraindications": "Limited modern research",
            "notes": "Promotes deep sleep. Take before bed.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/6178423/"
        },
        
        # Sexual Health
        {
            "name": "PT-141",
            "common_name": "Bremelanotide",
            "molecular_weight": 1025.0,
            "typical_dose_min": 500,
            "typical_dose_max": 2000,
            "frequency_per_day": 1,
            "half_life_hours": 3,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Libido enhancement, sexual arousal, works for both genders",
            "contraindications": "Hypertension; can cause nausea",
            "notes": "FDA-approved for female sexual dysfunction. Take 45min before activity.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/31348878/"
        },
        {
            "name": "Kisspeptin",
            "common_name": "Metastin",
            "molecular_weight": 1302.0,
            "typical_dose_min": 1000,
            "typical_dose_max": 6400,
            "frequency_per_day": 1,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Testosterone production, fertility, libido, puberty regulation",
            "contraindications": "Research peptide",
            "notes": "Stimulates GnRH release. Important for reproductive health.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/29045003/"
        },
        
        # Anti-Inflammatory & Immune
        {
            "name": "KPV",
            "common_name": "Alpha-MSH Tripeptide",
            "molecular_weight": 357.0,
            "typical_dose_min": 500,
            "typical_dose_max": 2000,
            "frequency_per_day": 2,
            "half_life_hours": 6,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Anti-inflammatory, gut health, IBD treatment, immune modulation",
            "contraindications": "Limited human data",
            "notes": "Potent anti-inflammatory. Good for gut issues.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/23439633/"
        },
        {
            "name": "Glutathione",
            "common_name": "GSH",
            "molecular_weight": 307.32,
            "typical_dose_min": 200,
            "typical_dose_max": 600,
            "frequency_per_day": 1,
            "half_life_hours": 2,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Master antioxidant, detoxification, skin brightening, immune support",
            "contraindications": "Generally safe",
            "notes": "Often combined with Vitamin C. Can be given IV for higher doses.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/28441668/"
        },
        {
            "name": "Thymosin Alpha-1",
            "common_name": "Tα1",
            "molecular_weight": 3108.0,
            "typical_dose_min": 1600,
            "typical_dose_max": 3200,
            "frequency_per_day": 1,
            "half_life_hours": 3,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Immune enhancement, antiviral, cancer support, chronic infections",
            "contraindications": "Autoimmune disorders (use cautiously)",
            "notes": "Powerful immune modulator. Used for chronic viral infections.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/23493191/"
        },
        {
            "name": "LL-37",
            "common_name": "Antimicrobial Peptide",
            "molecular_weight": 4493.0,
            "typical_dose_min": 200,
            "typical_dose_max": 500,
            "frequency_per_day": 1,
            "half_life_hours": 6,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Antimicrobial, wound healing, immune support, anti-biofilm",
            "contraindications": "Research peptide",
            "notes": "Natural antimicrobial peptide. Good for infections and wounds.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/17313687/"
        },
        {
            "name": "Thymalin",
            "common_name": "Thymus Extract",
            "molecular_weight": None,
            "typical_dose_min": 5000,
            "typical_dose_max": 10000,
            "frequency_per_day": 1,
            "half_life_hours": 12,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Immune restoration, thymus regeneration, anti-aging",
            "contraindications": "Autoimmune disorders",
            "notes": "Bioregulator peptide from Russia. Restores thymus function.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/25242146/"
        },
        {
            "name": "Pinealon",
            "common_name": "Brain Bioregulator",
            "molecular_weight": 384.0,
            "typical_dose_min": 10000,
            "typical_dose_max": 20000,
            "frequency_per_day": 1,
            "half_life_hours": 12,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Brain health, circadian rhythm, neuroprotection, longevity",
            "contraindications": "Limited Western research",
            "notes": "Russian bioregulator for brain and pineal gland.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/26529520/"
        },
        
        # Metabolic / Fat Loss
        {
            "name": "AOD-9604",
            "common_name": "Anti-Obesity Drug",
            "molecular_weight": 1815.0,
            "typical_dose_min": 250,
            "typical_dose_max": 500,
            "frequency_per_day": 1,
            "half_life_hours": 2,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Fat loss, lipolysis, joint repair, no appetite suppression",
            "contraindications": "Failed clinical trials but popular",
            "notes": "Fragment of HGH. Targets fat without affecting blood sugar.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/11129085/"
        },
        {
            "name": "5-Amino-1MQ",
            "common_name": "NNMT Inhibitor",
            "molecular_weight": 187.0,
            "typical_dose_min": 50,
            "typical_dose_max": 100,
            "frequency_per_day": 1,
            "half_life_hours": 24,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.ROOM_TEMP,
            "shelf_life_days": 365,
            "primary_benefits": "Metabolism boost, fat loss, increased NAD+, energy",
            "contraindications": "Very new; limited data",
            "notes": "Inhibits NNMT enzyme. Boosts cellular metabolism.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/31296053/"
        },
        {
            "name": "Tesofensine",
            "common_name": "Triple Reuptake Inhibitor",
            "molecular_weight": 295.0,
            "typical_dose_min": 250,
            "typical_dose_max": 1000,
            "frequency_per_day": 1,
            "half_life_hours": 24,
            "primary_route": AdministrationRoute.ORAL,
            "storage_method": StorageMethod.ROOM_TEMP,
            "shelf_life_days": 365,
            "primary_benefits": "Appetite suppression, weight loss, increased metabolism",
            "contraindications": "Cardiovascular concerns; monitor heart rate",
            "notes": "Triple monoamine reuptake inhibitor. Very effective for weight loss.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/18957192/"
        },
        {
            "name": "L-Carnitine",
            "common_name": "Levocarnitine",
            "molecular_weight": 161.2,
            "typical_dose_min": 500000,
            "typical_dose_max": 2000000,
            "frequency_per_day": 1,
            "half_life_hours": 15,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.ROOM_TEMP,
            "shelf_life_days": 365,
            "primary_benefits": "Fat metabolism, energy, athletic performance, mitochondrial health",
            "contraindications": "Generally safe; can cause fishy body odor",
            "notes": "Amino acid derivative. Transports fatty acids into mitochondria.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/28178352/"
        },
        
        # Growth Hormone Secretagogues
        {
            "name": "GHRP-2",
            "common_name": "Growth Hormone Releasing Peptide-2",
            "molecular_weight": 817.0,
            "typical_dose_min": 100,
            "typical_dose_max": 300,
            "frequency_per_day": 3,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "GH release, muscle growth, fat loss, recovery",
            "contraindications": "Monitor blood sugar",
            "notes": "Stimulates strong GH pulse. Take on empty stomach.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/9467543/"
        },
        {
            "name": "GHRP-6",
            "common_name": "Growth Hormone Releasing Peptide-6",
            "molecular_weight": 872.0,
            "typical_dose_min": 100,
            "typical_dose_max": 300,
            "frequency_per_day": 3,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "GH release, appetite increase, healing, anti-aging",
            "contraindications": "Increases hunger significantly",
            "notes": "Similar to GHRP-2 but with strong hunger effect.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/8841216/"
        },
        {
            "name": "Hexarelin",
            "common_name": "Examorelin",
            "molecular_weight": 887.0,
            "typical_dose_min": 100,
            "typical_dose_max": 200,
            "frequency_per_day": 2,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Strongest GH release, cardioprotection, neuroprotection",
            "contraindications": "Desensitization with prolonged use",
            "notes": "Most potent GHRP. Cycle 2 weeks on, 2 weeks off.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/9768483/"
        },
        
        # Muscle Growth
        {
            "name": "IGF-1 LR3",
            "common_name": "Long R3 IGF-I",
            "molecular_weight": 9111.0,
            "typical_dose_min": 20,
            "typical_dose_max": 100,
            "frequency_per_day": 1,
            "half_life_hours": 24,
            "primary_route": AdministrationRoute.SUBCUTANEOUS,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Muscle growth, hyperplasia, recovery, fat loss",
            "contraindications": "Hypoglycemia risk; monitor blood sugar",
            "notes": "Extended half-life IGF-1. Very potent for muscle growth.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/8181208/"
        },
        {
            "name": "IGF-1 DES",
            "common_name": "Des(1-3)IGF-I",
            "molecular_weight": 7372.0,
            "typical_dose_min": 50,
            "typical_dose_max": 150,
            "frequency_per_day": 2,
            "half_life_hours": 1,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Localized muscle growth, hyperplasia, intense pumps",
            "contraindications": "Hypoglycemia risk",
            "notes": "Short half-life. Inject into target muscle for local growth.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/2070441/"
        },
        {
            "name": "Follistatin-344",
            "common_name": "FST-344",
            "molecular_weight": 37800.0,
            "typical_dose_min": 100,
            "typical_dose_max": 200,
            "frequency_per_day": 1,
            "half_life_hours": 72,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.FREEZER,
            "shelf_life_days": 90,
            "primary_benefits": "Extreme muscle growth, myostatin inhibition",
            "contraindications": "Very expensive; limited availability",
            "notes": "Inhibits myostatin. Most powerful muscle growth peptide.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/22564864/"
        },
        
        # Joint Health
        {
            "name": "PPS",
            "common_name": "Pentosan Polysulfate",
            "molecular_weight": 4000.0,
            "typical_dose_min": 100,
            "typical_dose_max": 200,
            "frequency_per_day": 1,
            "half_life_hours": 24,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.ROOM_TEMP,
            "shelf_life_days": 365,
            "primary_benefits": "Joint health, cartilage repair, anti-inflammatory",
            "contraindications": "Bleeding disorders",
            "notes": "FDA-approved for interstitial cystitis. Used off-label for joints.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/16824524/"
        },
        
        # Cosmetic
        {
            "name": "Matrixyl",
            "common_name": "Palmitoyl Pentapeptide",
            "molecular_weight": 578.0,
            "typical_dose_min": None,
            "typical_dose_max": None,
            "frequency_per_day": 2,
            "half_life_hours": 12,
            "primary_route": AdministrationRoute.TOPICAL,
            "storage_method": StorageMethod.ROOM_TEMP,
            "shelf_life_days": 365,
            "primary_benefits": "Collagen synthesis, wrinkle reduction, skin firmness",
            "contraindications": "Generally safe",
            "notes": "Topical application. Popular in cosmetic formulations.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/15927579/"
        },
        {
            "name": "Argireline",
            "common_name": "Acetyl Hexapeptide-8",
            "molecular_weight": 888.0,
            "typical_dose_min": None,
            "typical_dose_max": None,
            "frequency_per_day": 2,
            "half_life_hours": 12,
            "primary_route": AdministrationRoute.TOPICAL,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 180,
            "primary_benefits": "Wrinkle reduction, muscle relaxation, Botox alternative",
            "contraindications": "Generally safe",
            "notes": "Topical 'Botox in a bottle'. Reduces expression lines.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/12445395/"
        },
        
        # Injectable Fat Loss Blends
        {
            "name": "Lipo-Shred",
            "common_name": "Lipotropic Fat Loss Blend",
            "molecular_weight": None,
            "typical_dose_min": 1000,
            "typical_dose_max": 2000,
            "frequency_per_day": 1,
            "half_life_hours": 12,
            "primary_route": AdministrationRoute.INTRAMUSCULAR,
            "storage_method": StorageMethod.REFRIGERATOR,
            "shelf_life_days": 30,
            "primary_benefits": "Fat metabolism, energy, liver support, weight loss",
            "contraindications": "Multiple ingredients; check individual sensitivities",
            "notes": "Typically contains: L-Carnitine, MIC (Methionine, Inositol, Choline), B12. Formulations vary.",
            "research_links": "https://pubmed.ncbi.nlm.nih.gov/25293431/"
        },
    ]
    
    print("\n" + "="*70)
    print("ADDING NEW PEPTIDES TO DATABASE")
    print("="*70 + "\n")
    
    added_count = 0
    skipped_count = 0
    
    for peptide_data in new_peptides:
        try:
            # Check if peptide already exists
            existing = db.get_peptide_by_name(peptide_data['name'])
            if existing:
                print(f"⊘ Skipped: {peptide_data['name']} (already exists)")
                skipped_count += 1
                continue
            
            peptide = db.add_peptide(**peptide_data)
            print(f"✓ Added: {peptide.name} ({peptide.common_name})")
            added_count += 1
            
        except Exception as e:
            print(f"✗ Error adding {peptide_data['name']}: {e}")
    
    print(f"\n{'='*70}")
    print(f"COMPLETE!")
    print(f"Added: {added_count} peptides")
    print(f"Skipped: {skipped_count} peptides (already in database)")
    print(f"Total peptides in database: {len(db.list_peptides())}")
    print("="*70 + "\n")
    
    session.close()


if __name__ == "__main__":
    add_new_peptides()
