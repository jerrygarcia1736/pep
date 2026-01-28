#!/usr/bin/env python3
"""
Example Usage Script
Demonstrates how to use the Peptide Tracker API programmatically
"""

from datetime import datetime
from models import get_session
from database import PeptideDB
from calculator import PeptideCalculator


def example_workflow():
    """Example workflow: Add vial, create protocol, log injections"""
    
    print("\n" + "="*70)
    print(" PEPTIDE TRACKER - EXAMPLE WORKFLOW")
    print("="*70)
    
    # Initialize database connection
    session = get_session("sqlite:///peptide_tracker.db")
    db = PeptideDB(session)
    
    # ========== STEP 1: Browse Available Peptides ==========
    print("\n[STEP 1] Browsing available peptides...")
    peptides = db.list_peptides()
    
    if not peptides:
        print("⚠ No peptides found! Run seed_data.py first.")
        return
    
    print(f"Found {len(peptides)} peptides in database:")
    for p in peptides[:5]:  # Show first 5
        print(f"  • {p.name} ({p.common_name})")
    
    # ========== STEP 2: Get Specific Peptide Details ==========
    print("\n[STEP 2] Getting BPC-157 details...")
    bpc = db.get_peptide_by_name("BPC-157")
    
    if bpc:
        print(f"✓ Found {bpc.name}")
        print(f"  Typical dose: {bpc.typical_dose_min}-{bpc.typical_dose_max} mcg")
        print(f"  Frequency: {bpc.frequency_per_day}x per day")
        print(f"  Half-life: {bpc.half_life_hours} hours")
    
    # ========== STEP 3: Calculate Reconstitution ==========
    print("\n[STEP 3] Calculating reconstitution for 5mg vial...")
    
    report = PeptideCalculator.full_reconstitution_report(
        peptide_name="BPC-157",
        mg_peptide=5,
        ml_water=2,
        desired_dose_mcg=250,
        doses_per_day=2
    )
    
    print(f"✓ Vial concentration: {report['concentration_mcg_per_ml']} mcg/ml")
    print(f"✓ Dose volume: {report['dose_volume_ml']} ml ({report['syringe_units']} units)")
    print(f"✓ Vial will last: {report['vial_lasts_days']} days")
    
    # ========== STEP 4: Add Vial to Database ==========
    print("\n[STEP 4] Adding vial to database...")
    
    vial = db.add_vial(
        peptide_id=bpc.id,
        mg_amount=5,
        bacteriostatic_water_ml=2,
        reconstitution_date=datetime.now(),
        vendor="Example Peptides Inc",
        lot_number="BP-2024-001"
    )
    
    print(f"✓ Vial added (ID: {vial.id})")
    print(f"  Concentration: {vial.concentration_mcg_per_ml} mcg/ml")
    print(f"  Expires: {vial.expiration_date.strftime('%Y-%m-%d') if vial.expiration_date else 'N/A'}")
    
    # ========== STEP 5: Create Protocol ==========
    print("\n[STEP 5] Creating injury recovery protocol...")
    
    protocol = db.create_protocol(
        peptide_id=bpc.id,
        name="BPC-157 Shoulder Recovery",
        dose_mcg=250,
        frequency_per_day=2,
        duration_days=30,
        goals="Heal rotator cuff strain, reduce inflammation",
        notes="Injecting near injury site"
    )
    
    print(f"✓ Protocol created (ID: {protocol.id})")
    print(f"  Name: {protocol.name}")
    print(f"  Duration: {protocol.duration_days} days")
    print(f"  Ends: {protocol.end_date.strftime('%Y-%m-%d')}")
    
    # ========== STEP 6: Log Injections ==========
    print("\n[STEP 6] Logging sample injections...")
    
    # Morning injection
    inj1 = db.log_injection(
        protocol_id=protocol.id,
        vial_id=vial.id,
        dose_mcg=250,
        volume_ml=0.1,
        injection_site="right shoulder (anterior)",
        subjective_notes="No pain, slight warmth at injection site"
    )
    
    print(f"✓ Morning injection logged (ID: {inj1.id})")
    
    # Evening injection
    inj2 = db.log_injection(
        protocol_id=protocol.id,
        vial_id=vial.id,
        dose_mcg=250,
        volume_ml=0.1,
        injection_site="right shoulder (posterior)",
        subjective_notes="Feeling better mobility after 1 week"
    )
    
    print(f"✓ Evening injection logged (ID: {inj2.id})")
    print(f"  Vial remaining: {vial.remaining_ml} ml")
    
    # ========== STEP 7: View Protocol History ==========
    print("\n[STEP 7] Viewing protocol injection history...")
    
    injections = db.get_protocol_injections(protocol.id, limit=5)
    print(f"✓ Found {len(injections)} recent injections:")
    
    for inj in injections:
        print(f"  • {inj.timestamp.strftime('%Y-%m-%d %H:%M')} - {inj.dose_mcg} mcg")
        if inj.subjective_notes:
            print(f"    Notes: {inj.subjective_notes}")
    
    # ========== STEP 8: Add Research Note ==========
    print("\n[STEP 8] Adding research note...")
    
    note = db.add_research_note(
        peptide_id=bpc.id,
        title="BPC-157 Efficacy in Tendon Healing",
        content="Study shows BPC-157 accelerates healing of Achilles tendon tears in rat models. "
                "Mechanism involves increased VEGF expression and collagen organization.",
        source_url="https://pubmed.ncbi.nlm.nih.gov/31633635/",
        source_type="study",
        tags="tendon, healing, injury, rats"
    )
    
    print(f"✓ Research note added (ID: {note.id})")
    
    # ========== Summary ==========
    print("\n" + "="*70)
    print(" WORKFLOW COMPLETE!")
    print("="*70)
    print("\nWhat we did:")
    print("  ✓ Browsed peptide database")
    print("  ✓ Calculated reconstitution")
    print("  ✓ Added vial to inventory")
    print("  ✓ Created dosing protocol")
    print("  ✓ Logged injections")
    print("  ✓ Stored research notes")
    print("\nNext steps:")
    print("  • Run cli.py for interactive management")
    print("  • Check peptide_tracker.db for all stored data")
    print("  • Add more protocols and track your progress!")
    print("="*70 + "\n")
    
    # Clean up
    session.close()


def example_queries():
    """Example queries and reports"""
    
    print("\n" + "="*70)
    print(" EXAMPLE QUERIES")
    print("="*70)
    
    session = get_session("sqlite:///peptide_tracker.db")
    db = PeptideDB(session)
    
    # Active protocols
    print("\n[Query 1] Active Protocols:")
    protocols = db.list_active_protocols()
    for p in protocols:
        print(f"  • {p.name} - {p.peptide.name}")
        print(f"    {p.dose_mcg} mcg, {p.frequency_per_day}x/day")
    
    # Recent injections
    print("\n[Query 2] Last 7 days of injections:")
    recent = db.get_recent_injections(days=7)
    for inj in recent:
        print(f"  • {inj.timestamp.strftime('%Y-%m-%d')}: {inj.protocol.peptide.name} - {inj.dose_mcg} mcg")
    
    # Active vials
    print("\n[Query 3] Active vials:")
    vials = db.list_active_vials()
    for v in vials:
        print(f"  • {v.peptide.name}: {v.mg_amount}mg ({v.remaining_ml}ml remaining)")
    
    session.close()
    print()


if __name__ == "__main__":
    # Check if database exists
    import os
    if not os.path.exists("peptide_tracker.db"):
        print("\n⚠ Database not found! Please run: python seed_data.py")
        print()
    else:
        example_workflow()
        example_queries()
