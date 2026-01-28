"""
Peptide Calculator
Handles reconstitution and dosing calculations
"""

from typing import Optional, Dict, Tuple


class PeptideCalculator:
    """Calculate peptide reconstitution and dosing"""
    
    @staticmethod
    def calculate_concentration(mg_peptide: float, ml_water: float) -> float:
        """
        Calculate concentration after reconstitution
        
        Args:
            mg_peptide: Amount of peptide in milligrams
            ml_water: Amount of bacteriostatic water in milliliters
            
        Returns:
            Concentration in mcg/ml
        """
        if ml_water <= 0:
            raise ValueError("Water volume must be greater than 0")
        
        # Convert mg to mcg (1 mg = 1000 mcg)
        mcg_peptide = mg_peptide * 1000
        concentration = mcg_peptide / ml_water
        return round(concentration, 2)
    
    @staticmethod
    def calculate_dose_volume(desired_dose_mcg: float, concentration_mcg_per_ml: float) -> float:
        """
        Calculate volume needed for desired dose
        
        Args:
            desired_dose_mcg: Desired dose in micrograms
            concentration_mcg_per_ml: Concentration in mcg/ml
            
        Returns:
            Volume in milliliters
        """
        if concentration_mcg_per_ml <= 0:
            raise ValueError("Concentration must be greater than 0")
        
        volume_ml = desired_dose_mcg / concentration_mcg_per_ml
        return round(volume_ml, 3)
    
    @staticmethod
    def calculate_units_on_syringe(volume_ml: float, syringe_type: str = "insulin") -> float:
        """
        Convert ml to insulin syringe units
        
        Args:
            volume_ml: Volume in milliliters
            syringe_type: Type of syringe ("insulin" for 100 unit = 1ml)
            
        Returns:
            Units on syringe
        """
        if syringe_type == "insulin":
            # Standard insulin syringe: 100 units = 1 ml
            units = volume_ml * 100
            return round(units, 1)
        else:
            raise ValueError(f"Unknown syringe type: {syringe_type}")
    
    @staticmethod
    def calculate_total_doses(mg_peptide: float, dose_mcg: float) -> int:
        """
        Calculate how many doses are in a vial
        
        Args:
            mg_peptide: Amount of peptide in vial (mg)
            dose_mcg: Dose per injection (mcg)
            
        Returns:
            Number of doses
        """
        mcg_peptide = mg_peptide * 1000
        total_doses = int(mcg_peptide / dose_mcg)
        return total_doses
    
    @staticmethod
    def calculate_vial_duration(
        total_doses: int, 
        doses_per_day: int
    ) -> float:
        """
        Calculate how many days a vial will last
        
        Args:
            total_doses: Total number of doses in vial
            doses_per_day: How many doses per day
            
        Returns:
            Days the vial will last
        """
        if doses_per_day <= 0:
            raise ValueError("Doses per day must be greater than 0")
        
        days = total_doses / doses_per_day
        return round(days, 1)
    
    @staticmethod
    def full_reconstitution_report(
        peptide_name: str,
        mg_peptide: float,
        ml_water: float,
        desired_dose_mcg: float,
        doses_per_day: int = 1
    ) -> Dict[str, any]:
        """
        Generate a complete reconstitution and dosing report
        
        Args:
            peptide_name: Name of the peptide
            mg_peptide: Amount of peptide in vial (mg)
            ml_water: Amount of bacteriostatic water to add (ml)
            desired_dose_mcg: Desired dose per injection (mcg)
            doses_per_day: Number of doses per day
            
        Returns:
            Dictionary with all calculations
        """
        calc = PeptideCalculator
        
        concentration = calc.calculate_concentration(mg_peptide, ml_water)
        dose_volume = calc.calculate_dose_volume(desired_dose_mcg, concentration)
        syringe_units = calc.calculate_units_on_syringe(dose_volume)
        total_doses = calc.calculate_total_doses(mg_peptide, desired_dose_mcg)
        days_lasting = calc.calculate_vial_duration(total_doses, doses_per_day)
        
        return {
            "peptide": peptide_name,
            "vial_size_mg": mg_peptide,
            "water_added_ml": ml_water,
            "concentration_mcg_per_ml": concentration,
            "target_dose_mcg": desired_dose_mcg,
            "dose_volume_ml": dose_volume,
            "syringe_units": syringe_units,
            "total_doses_in_vial": total_doses,
            "doses_per_day": doses_per_day,
            "vial_lasts_days": days_lasting,
        }
    
    @staticmethod
    def print_reconstitution_report(report: Dict[str, any]) -> None:
        """Print a formatted reconstitution report"""
        print(f"\n{'='*60}")
        print(f"PEPTIDE RECONSTITUTION REPORT: {report['peptide']}")
        print(f"{'='*60}")
        print(f"\nVIAL PREPARATION:")
        print(f"  • Peptide amount: {report['vial_size_mg']} mg")
        print(f"  • Bacteriostatic water: {report['water_added_ml']} ml")
        print(f"  • Final concentration: {report['concentration_mcg_per_ml']} mcg/ml")
        print(f"\nDOSING INSTRUCTIONS:")
        print(f"  • Target dose: {report['target_dose_mcg']} mcg")
        print(f"  • Inject volume: {report['dose_volume_ml']} ml")
        print(f"  • Syringe units: {report['syringe_units']} units (on insulin syringe)")
        print(f"  • Frequency: {report['doses_per_day']}x per day")
        print(f"\nVIAL LIFESPAN:")
        print(f"  • Total doses available: {report['total_doses_in_vial']}")
        print(f"  • Vial will last: {report['vial_lasts_days']} days")
        print(f"{'='*60}\n")


def interactive_calculator():
    """Interactive command-line calculator"""
    print("\n" + "="*60)
    print("PEPTIDE RECONSTITUTION CALCULATOR")
    print("="*60)
    
    peptide_name = input("\nEnter peptide name (e.g., BPC-157): ").strip()
    
    try:
        mg_peptide = float(input("Enter peptide amount in vial (mg): "))
        ml_water = float(input("Enter bacteriostatic water to add (ml): "))
        desired_dose_mcg = float(input("Enter desired dose per injection (mcg): "))
        doses_per_day = int(input("Enter doses per day: "))
        
        report = PeptideCalculator.full_reconstitution_report(
            peptide_name, mg_peptide, ml_water, desired_dose_mcg, doses_per_day
        )
        
        PeptideCalculator.print_reconstitution_report(report)
        
    except ValueError as e:
        print(f"\n❌ Error: {e}")
        print("Please enter valid numbers.")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")


if __name__ == "__main__":
    # Run interactive calculator if executed directly
    interactive_calculator()
    
    # Example usage
    print("\n" + "="*60)
    print("EXAMPLE CALCULATIONS:")
    print("="*60)
    
    # Example: BPC-157
    example = PeptideCalculator.full_reconstitution_report(
        peptide_name="BPC-157",
        mg_peptide=5,
        ml_water=2,
        desired_dose_mcg=250,
        doses_per_day=2
    )
    PeptideCalculator.print_reconstitution_report(example)
