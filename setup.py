#!/usr/bin/env python3
"""
Quick Setup Script for Peptide Tracker
Initializes database and seeds with common peptides
"""

import os
import sys

def main():
    print("\n" + "="*70)
    print(" PEPTIDE TRACKER - QUICK SETUP")
    print("="*70)
    
    print("\nThis script will:")
    print("1. Install required Python packages")
    print("2. Create SQLite database")
    print("3. Seed database with 10+ common peptides")
    print("4. Run a test calculation")
    
    response = input("\nContinue? (y/n): ").strip().lower()
    if response != 'y':
        print("Setup cancelled.")
        return
    
    print("\n" + "-"*70)
    print("Step 1: Installing dependencies...")
    print("-"*70)
    os.system(f"{sys.executable} -m pip install -q -r requirements.txt")
    print("✓ Dependencies installed")
    
    print("\n" + "-"*70)
    print("Step 2: Creating database and seeding peptides...")
    print("-"*70)
    os.system(f"{sys.executable} seed_data.py")
    
    print("\n" + "-"*70)
    print("Step 3: Testing calculator...")
    print("-"*70)
    
    from calculator import PeptideCalculator
    
    report = PeptideCalculator.full_reconstitution_report(
        peptide_name="BPC-157",
        mg_peptide=5,
        ml_water=2,
        desired_dose_mcg=250,
        doses_per_day=2
    )
    
    PeptideCalculator.print_reconstitution_report(report)
    
    print("\n" + "="*70)
    print(" SETUP COMPLETE!")
    print("="*70)
    print("\nYou can now:")
    print("  • Run the CLI: python cli.py")
    print("  • Use the calculator: python calculator.py")
    print("  • View README.md for usage examples")
    print("\nDatabase file: peptide_tracker.db")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
