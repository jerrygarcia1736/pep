"""
Database Operations
CRUD operations for peptide management
"""

from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from models import Peptide, Vial, Protocol, Injection, ResearchNote
from models import AdministrationRoute, StorageMethod


class PeptideDB:
    """Database operations for peptides"""
    
    def __init__(self, session: Session):
        self.session = session
    
    # ==================== PEPTIDE OPERATIONS ====================
    
    def add_peptide(
        self,
        name: str,
        common_name: Optional[str] = None,
        molecular_weight: Optional[float] = None,
        typical_dose_min: Optional[float] = None,
        typical_dose_max: Optional[float] = None,
        frequency_per_day: Optional[int] = None,
        half_life_hours: Optional[float] = None,
        primary_route: Optional[AdministrationRoute] = None,
        storage_method: Optional[StorageMethod] = None,
        shelf_life_days: Optional[int] = None,
        primary_benefits: Optional[str] = None,
        contraindications: Optional[str] = None,
        notes: Optional[str] = None,
        research_links: Optional[str] = None
    ) -> Peptide:
        """Add a new peptide to the database"""
        peptide = Peptide(
            name=name,
            common_name=common_name,
            molecular_weight=molecular_weight,
            typical_dose_min=typical_dose_min,
            typical_dose_max=typical_dose_max,
            frequency_per_day=frequency_per_day,
            half_life_hours=half_life_hours,
            primary_route=primary_route,
            storage_method=storage_method,
            shelf_life_days=shelf_life_days,
            primary_benefits=primary_benefits,
            contraindications=contraindications,
            notes=notes,
            research_links=research_links
        )
        
        self.session.add(peptide)
        self.session.commit()
        return peptide
    
    def get_peptide(self, peptide_id: int) -> Optional[Peptide]:
        """Get peptide by ID"""
        return self.session.query(Peptide).filter(Peptide.id == peptide_id).first()
    
    def get_peptide_by_name(self, name: str) -> Optional[Peptide]:
        """Get peptide by name"""
        return self.session.query(Peptide).filter(Peptide.name == name).first()
    
    def list_peptides(self) -> List[Peptide]:
        """List all peptides"""
        return self.session.query(Peptide).all()
    
    def update_peptide(self, peptide_id: int, **kwargs) -> Optional[Peptide]:
        """Update peptide attributes"""
        peptide = self.get_peptide(peptide_id)
        if peptide:
            for key, value in kwargs.items():
                if hasattr(peptide, key):
                    setattr(peptide, key, value)
            peptide.updated_at = datetime.utcnow()
            self.session.commit()
        return peptide
    
    def delete_peptide(self, peptide_id: int) -> bool:
        """Delete a peptide"""
        peptide = self.get_peptide(peptide_id)
        if peptide:
            self.session.delete(peptide)
            self.session.commit()
            return True
        return False
    
    # ==================== VIAL OPERATIONS ====================
    
    def add_vial(
        self,
        peptide_id: int,
        mg_amount: float,
        bacteriostatic_water_ml: Optional[float] = None,
        purchase_date: Optional[datetime] = None,
        reconstitution_date: Optional[datetime] = None,
        lot_number: Optional[str] = None,
        vendor: Optional[str] = None,
        cost: Optional[float] = None,
        notes: Optional[str] = None
    ) -> Vial:
        """Add a new vial"""
        vial = Vial(
            peptide_id=peptide_id,
            mg_amount=mg_amount,
            bacteriostatic_water_ml=bacteriostatic_water_ml,
            purchase_date=purchase_date,
            reconstitution_date=reconstitution_date,
            lot_number=lot_number,
            vendor=vendor,
            cost=cost,
            notes=notes,
            remaining_ml=bacteriostatic_water_ml
        )
        
        # Calculate concentration and expiration if reconstituted
        if bacteriostatic_water_ml:
            vial.calculate_concentration()
            
            if reconstitution_date:
                peptide = self.get_peptide(peptide_id)
                if peptide and peptide.shelf_life_days:
                    vial.expiration_date = reconstitution_date + timedelta(days=peptide.shelf_life_days)
        
        self.session.add(vial)
        self.session.commit()
        return vial
    
    def get_vial(self, vial_id: int) -> Optional[Vial]:
        """Get vial by ID"""
        return self.session.query(Vial).filter(Vial.id == vial_id).first()
    
    def list_active_vials(self, peptide_id: Optional[int] = None) -> List[Vial]:
        """List active vials, optionally filtered by peptide"""
        query = self.session.query(Vial).filter(Vial.is_active == True)
        if peptide_id:
            query = query.filter(Vial.peptide_id == peptide_id)
        return query.all()
    
    def reconstitute_vial(
        self,
        vial_id: int,
        bacteriostatic_water_ml: float,
        reconstitution_date: Optional[datetime] = None
    ) -> Optional[Vial]:
        """Reconstitute a vial"""
        vial = self.get_vial(vial_id)
        if vial:
            vial.bacteriostatic_water_ml = bacteriostatic_water_ml
            vial.remaining_ml = bacteriostatic_water_ml
            vial.reconstitution_date = reconstitution_date or datetime.utcnow()
            vial.calculate_concentration()
            
            # Set expiration date
            peptide = self.get_peptide(vial.peptide_id)
            if peptide and peptide.shelf_life_days:
                vial.expiration_date = vial.reconstitution_date + timedelta(days=peptide.shelf_life_days)
            
            self.session.commit()
        return vial
    
    def deactivate_vial(self, vial_id: int) -> Optional[Vial]:
        """Mark vial as inactive (used up or expired)"""
        vial = self.get_vial(vial_id)
        if vial:
            vial.is_active = False
            self.session.commit()
        return vial
    
    # ==================== PROTOCOL OPERATIONS ====================
    
    def create_protocol(
        self,
        peptide_id: int,
        name: str,
        dose_mcg: float,
        frequency_per_day: int,
        description: Optional[str] = None,
        duration_days: Optional[int] = None,
        start_date: Optional[datetime] = None,
        goals: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Protocol:
        """Create a new protocol"""
        protocol = Protocol(
            peptide_id=peptide_id,
            name=name,
            description=description,
            dose_mcg=dose_mcg,
            frequency_per_day=frequency_per_day,
            duration_days=duration_days,
            start_date=start_date or datetime.utcnow(),
            goals=goals,
            notes=notes
        )
        
        if duration_days and start_date:
            protocol.end_date = start_date + timedelta(days=duration_days)
        
        self.session.add(protocol)
        self.session.commit()
        return protocol
    
    def get_protocol(self, protocol_id: int) -> Optional[Protocol]:
        """Get protocol by ID"""
        return self.session.query(Protocol).filter(Protocol.id == protocol_id).first()
    
    def list_active_protocols(self) -> List[Protocol]:
        """List all active protocols"""
        # Eager-load related Peptide to avoid DetachedInstanceError when templates
        # access protocol.peptide after the request/session lifecycle.
        return (
            self.session.query(Protocol)
            .options(joinedload(Protocol.peptide))
            .filter(Protocol.is_active == True)
            .order_by(Protocol.start_date.desc())
            .all()
        )
    
    def complete_protocol(self, protocol_id: int) -> Optional[Protocol]:
        """Mark protocol as complete"""
        protocol = self.get_protocol(protocol_id)
        if protocol:
            protocol.is_active = False
            protocol.end_date = datetime.utcnow()
            self.session.commit()
        return protocol
    
    # ==================== INJECTION LOGGING ====================
    
    def log_injection(
        self,
        protocol_id: int,
        vial_id: int,
        dose_mcg: float,
        volume_ml: float,
        injection_site: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        side_effects: Optional[str] = None,
        subjective_notes: Optional[str] = None
    ) -> Injection:
        """Log an injection"""
        injection = Injection(
            protocol_id=protocol_id,
            vial_id=vial_id,
            timestamp=timestamp or datetime.utcnow(),
            dose_mcg=dose_mcg,
            volume_ml=volume_ml,
            injection_site=injection_site,
            side_effects=side_effects,
            subjective_notes=subjective_notes
        )
        
        # Update vial remaining volume
        vial = self.get_vial(vial_id)
        if vial and vial.remaining_ml:
            vial.remaining_ml -= volume_ml
            if vial.remaining_ml <= 0:
                vial.is_active = False
        
        self.session.add(injection)
        self.session.commit()
        return injection
    
    def get_protocol_injections(
        self,
        protocol_id: int,
        limit: Optional[int] = None
    ) -> List[Injection]:
        """Get injections for a protocol"""
        query = self.session.query(Injection).filter(
            Injection.protocol_id == protocol_id
        ).order_by(Injection.timestamp.desc())
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    
    def get_recent_injections(self, days: int = 7) -> List[Injection]:
        """Get recent injections within X days"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        return self.session.query(Injection).filter(
            Injection.timestamp >= cutoff
        ).order_by(Injection.timestamp.desc()).all()
    
    # ==================== RESEARCH NOTES ====================
    
    def add_research_note(
        self,
        title: str,
        content: str,
        peptide_id: Optional[int] = None,
        source_url: Optional[str] = None,
        source_type: Optional[str] = None,
        tags: Optional[str] = None
    ) -> ResearchNote:
        """Add a research note"""
        note = ResearchNote(
            peptide_id=peptide_id,
            title=title,
            content=content,
            source_url=source_url,
            source_type=source_type,
            tags=tags
        )
        
        self.session.add(note)
        self.session.commit()
        return note
    
    def search_research_notes(self, query: str) -> List[ResearchNote]:
        """Search research notes by keyword"""
        return self.session.query(ResearchNote).filter(
            ResearchNote.content.contains(query) | 
            ResearchNote.title.contains(query)
        ).all()
    
    def get_peptide_research(self, peptide_id: int) -> List[ResearchNote]:
        """Get all research notes for a peptide"""
        return self.session.query(ResearchNote).filter(
            ResearchNote.peptide_id == peptide_id
        ).all()


# Convenience functions for common operations
def quick_add_peptide(session: Session, name: str, **kwargs) -> Peptide:
    """Quick add peptide with common defaults"""
    db = PeptideDB(session)
    return db.add_peptide(name=name, **kwargs)


def quick_add_vial(
    session: Session,
    peptide_name: str,
    mg_amount: float,
    **kwargs
) -> Optional[Vial]:
    """Quick add vial by peptide name"""
    db = PeptideDB(session)
    peptide = db.get_peptide_by_name(peptide_name)
    
    if peptide:
        return db.add_vial(peptide_id=peptide.id, mg_amount=mg_amount, **kwargs)
    else:
        print(f"Peptide '{peptide_name}' not found!")
        return None
