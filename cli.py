#!/usr/bin/env python3
"""
Peptide Tracker CLI
Command-line interface for managing peptides
"""

import sys
from datetime import datetime
from models import get_session
from database import PeptideDB
from calculator import PeptideCalculator
from config import Config


class PeptideCLI:
    """Command-line interface for peptide management"""
    
    def __init__(self, use_sqlite=True):
        """Initialize CLI with database session"""
        if use_sqlite:
            self.db_url = "sqlite:///peptide_tracker.db"
        else:
            self.db_url = Config.DATABASE_URL
        
        self.session = get_session(self.db_url)
        self.db = PeptideDB(self.session)
    
    def run(self):
        """Main CLI loop"""
        print("\n" + "="*60)
        print("PEPTIDE TRACKER CLI")
        print("="*60)
        
        while True:
            print("\nMAIN MENU:")
            print("1. List all peptides")
            print("2. View peptide details")
            print("3. Calculate reconstitution")
            print("4. Add vial")
            print("5. Create protocol")
            print("6. Log injection")
            print("7. View active protocols")
            print("8. View recent injections")
            print("9. Exit")
            
            choice = input("\nSelect option (1-9): ").strip()
            
            if choice == "1":
                self.list_peptides()
            elif choice == "2":
                self.view_peptide()
            elif choice == "3":
                self.calculate_reconstitution()
            elif choice == "4":
                self.add_vial()
            elif choice == "5":
                self.create_protocol()
            elif choice == "6":
                self.log_injection()
            elif choice == "7":
                self.view_protocols()
            elif choice == "8":
                self.view_injections()
            elif choice == "9":
                print("\nGoodbye!")
                break
            else:
                print("Invalid option. Please try again.")
    
    def list_peptides(self):
        """List all peptides in database"""
        peptides = self.db.list_peptides()
        
        if not peptides:
            print("\n⚠ No peptides in database. Run seed_data.py to add common peptides.")
            return
        
        print("\n" + "="*60)
        print("AVAILABLE PEPTIDES")
        print("="*60)
        
        for i, p in enumerate(peptides, 1):
            dose_range = f"{p.typical_dose_min}-{p.typical_dose_max} mcg" if p.typical_dose_min else "N/A"
            print(f"{i}. {p.name} ({p.common_name})")
            print(f"   Typical dose: {dose_range}")
            print(f"   Route: {p.primary_route.value if p.primary_route else 'N/A'}")
            print()
    
    def view_peptide(self):
        """View detailed peptide information"""
        name = input("\nEnter peptide name: ").strip()
        peptide = self.db.get_peptide_by_name(name)
        
        if not peptide:
            print(f"\n⚠ Peptide '{name}' not found.")
            return
        
        print("\n" + "="*60)
        print(f"PEPTIDE DETAILS: {peptide.name}")
        print("="*60)
        print(f"Common name: {peptide.common_name}")
        print(f"Molecular weight: {peptide.molecular_weight} Da")
        print(f"Typical dose: {peptide.typical_dose_min}-{peptide.typical_dose_max} mcg")
        print(f"Frequency: {peptide.frequency_per_day}x per day")
        print(f"Half-life: {peptide.half_life_hours} hours")
        print(f"Route: {peptide.primary_route.value if peptide.primary_route else 'N/A'}")
        print(f"Storage: {peptide.storage_method.value if peptide.storage_method else 'N/A'}")
        print(f"Shelf life (reconstituted): {peptide.shelf_life_days} days")
        print(f"\nBenefits: {peptide.primary_benefits}")
        print(f"\nContraindications: {peptide.contraindications}")
        print(f"\nNotes: {peptide.notes}")
    
    def calculate_reconstitution(self):
        """Interactive reconstitution calculator"""
        print("\n" + "="*60)
        print("RECONSTITUTION CALCULATOR")
        print("="*60)
        
        try:
            peptide_name = input("\nPeptide name: ").strip()
            mg_amount = float(input("Vial size (mg): "))
            ml_water = float(input("Bacteriostatic water to add (ml): "))
            dose_mcg = float(input("Desired dose per injection (mcg): "))
            doses_per_day = int(input("Doses per day: "))
            
            report = PeptideCalculator.full_reconstitution_report(
                peptide_name, mg_amount, ml_water, dose_mcg, doses_per_day
            )
            
            PeptideCalculator.print_reconstitution_report(report)
            
        except ValueError as e:
            print(f"\n⚠ Error: {e}")
    
    def add_vial(self):
        """Add a new vial"""
        print("\n" + "="*60)
        print("ADD NEW VIAL")
        print("="*60)
        
        peptide_name = input("\nPeptide name: ").strip()
        peptide = self.db.get_peptide_by_name(peptide_name)
        
        if not peptide:
            print(f"\n⚠ Peptide '{peptide_name}' not found.")
            return
        
        try:
            mg_amount = float(input("Vial size (mg): "))
            vendor = input("Vendor (optional): ").strip() or None
            lot = input("Lot number (optional): ").strip() or None
            
            reconstitute = input("Reconstitute now? (y/n): ").strip().lower()
            
            if reconstitute == 'y':
                ml_water = float(input("Bacteriostatic water (ml): "))
                vial = self.db.add_vial(
                    peptide_id=peptide.id,
                    mg_amount=mg_amount,
                    bacteriostatic_water_ml=ml_water,
                    reconstitution_date=datetime.now(),
                    vendor=vendor,
                    lot_number=lot
                )
            else:
                vial = self.db.add_vial(
                    peptide_id=peptide.id,
                    mg_amount=mg_amount,
                    vendor=vendor,
                    lot_number=lot
                )
            
            print(f"\n✓ Vial added successfully! (ID: {vial.id})")
            if vial.concentration_mcg_per_ml:
                print(f"  Concentration: {vial.concentration_mcg_per_ml} mcg/ml")
            
        except ValueError as e:
            print(f"\n⚠ Error: {e}")
    
    def create_protocol(self):
        """Create a new protocol"""
        print("\n" + "="*60)
        print("CREATE NEW PROTOCOL")
        print("="*60)
        
        peptide_name = input("\nPeptide name: ").strip()
        peptide = self.db.get_peptide_by_name(peptide_name)
        
        if not peptide:
            print(f"\n⚠ Peptide '{peptide_name}' not found.")
            return
        
        try:
            name = input("Protocol name: ").strip()
            dose_mcg = float(input("Dose per injection (mcg): "))
            frequency = int(input("Injections per day: "))
            duration = int(input("Duration (days): "))
            goals = input("Goals (optional): ").strip() or None
            
            protocol = self.db.create_protocol(
                peptide_id=peptide.id,
                name=name,
                dose_mcg=dose_mcg,
                frequency_per_day=frequency,
                duration_days=duration,
                goals=goals,
                start_date=datetime.now()
            )
            
            print(f"\n✓ Protocol created successfully! (ID: {protocol.id})")
            print(f"  Running until: {protocol.end_date.strftime('%Y-%m-%d')}")
            
        except ValueError as e:
            print(f"\n⚠ Error: {e}")
    
    def log_injection(self):
        """Log an injection"""
        print("\n" + "="*60)
        print("LOG INJECTION")
        print("="*60)
        
        # Show active protocols
        protocols = self.db.list_active_protocols()
        if not protocols:
            print("\n⚠ No active protocols. Create one first.")
            return
        
        print("\nActive Protocols:")
        for i, p in enumerate(protocols, 1):
            print(f"{i}. {p.name} - {p.peptide.name} ({p.dose_mcg} mcg, {p.frequency_per_day}x/day)")
        
        try:
            protocol_idx = int(input("\nSelect protocol (number): ")) - 1
            protocol = protocols[protocol_idx]
            
            # Show active vials for this peptide
            vials = self.db.list_active_vials(protocol.peptide_id)
            if not vials:
                print(f"\n⚠ No active vials for {protocol.peptide.name}. Add a vial first.")
                return
            
            print("\nActive Vials:")
            for i, v in enumerate(vials, 1):
                print(f"{i}. {v.mg_amount}mg - {v.concentration_mcg_per_ml} mcg/ml ({v.remaining_ml}ml remaining)")
            
            vial_idx = int(input("Select vial (number): ")) - 1
            vial = vials[vial_idx]
            
            # Calculate volume for protocol dose
            volume_ml = vial.calculate_dose_volume(protocol.dose_mcg)
            units = PeptideCalculator.calculate_units_on_syringe(volume_ml)
            
            print(f"\nDose: {protocol.dose_mcg} mcg = {volume_ml} ml = {units} units")
            
            site = input("Injection site (optional): ").strip() or None
            notes = input("Notes (optional): ").strip() or None
            
            injection = self.db.log_injection(
                protocol_id=protocol.id,
                vial_id=vial.id,
                dose_mcg=protocol.dose_mcg,
                volume_ml=volume_ml,
                injection_site=site,
                subjective_notes=notes
            )
            
            print(f"\n✓ Injection logged successfully! (ID: {injection.id})")
            print(f"  Vial remaining: {vial.remaining_ml} ml")
            
        except (ValueError, IndexError) as e:
            print(f"\n⚠ Error: {e}")
    
    def view_protocols(self):
        """View active protocols"""
        protocols = self.db.list_active_protocols()
        
        if not protocols:
            print("\n⚠ No active protocols.")
            return
        
        print("\n" + "="*60)
        print("ACTIVE PROTOCOLS")
        print("="*60)
        
        for p in protocols:
            print(f"\n{p.name}")
            print(f"  Peptide: {p.peptide.name}")
            print(f"  Dose: {p.dose_mcg} mcg, {p.frequency_per_day}x per day")
            print(f"  Started: {p.start_date.strftime('%Y-%m-%d')}")
            if p.end_date:
                print(f"  Ends: {p.end_date.strftime('%Y-%m-%d')}")
            if p.goals:
                print(f"  Goals: {p.goals}")
    
    def view_injections(self):
        """View recent injections"""
        days = int(input("\nShow injections from last X days (default 7): ").strip() or "7")
        
        injections = self.db.get_recent_injections(days)
        
        if not injections:
            print(f"\n⚠ No injections in the last {days} days.")
            return
        
        print("\n" + "="*60)
        print(f"INJECTIONS (LAST {days} DAYS)")
        print("="*60)
        
        for inj in injections:
            print(f"\n{inj.timestamp.strftime('%Y-%m-%d %H:%M')}")
            print(f"  Protocol: {inj.protocol.name}")
            print(f"  Peptide: {inj.protocol.peptide.name}")
            print(f"  Dose: {inj.dose_mcg} mcg ({inj.volume_ml} ml)")
            if inj.injection_site:
                print(f"  Site: {inj.injection_site}")
            if inj.subjective_notes:
                print(f"  Notes: {inj.subjective_notes}")
    
    def close(self):
        """Close database session"""
        self.session.close()


def main():
    """Run CLI application"""
    cli = PeptideCLI(use_sqlite=True)
    
    try:
        cli.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
    finally:
        cli.close()


if __name__ == "__main__":
    main()
