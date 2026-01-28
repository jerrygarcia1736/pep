"""
Peptide Tracker Database Models
SQLAlchemy ORM models for peptide management and tracking
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, 
    DateTime, Boolean, ForeignKey, Enum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import enum

Base = declarative_base()


class StorageMethod(enum.Enum):
    """How peptide should be stored"""
    FREEZER = "freezer"
    REFRIGERATOR = "refrigerator"
    ROOM_TEMP = "room_temp"


class AdministrationRoute(enum.Enum):
    """How peptide is administered"""
    SUBCUTANEOUS = "subcutaneous"
    INTRAMUSCULAR = "intramuscular"
    ORAL = "oral"
    NASAL = "nasal"
    TOPICAL = "topical"


class Peptide(Base):
    """Master peptide information"""
    __tablename__ = 'peptides'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    common_name = Column(String(100))  # e.g., "BPC-157" vs "Pentadecapeptide BPC 157"
    molecular_weight = Column(Float)  # Daltons
    sequence = Column(Text)  # Amino acid sequence if known
    
    # Dosing information
    typical_dose_min = Column(Float)  # mcg
    typical_dose_max = Column(Float)  # mcg
    frequency_per_day = Column(Integer)  # How many times per day
    half_life_hours = Column(Float)
    
    # Administration
    primary_route = Column(Enum(AdministrationRoute))
    
    # Storage
    storage_method = Column(Enum(StorageMethod))
    shelf_life_days = Column(Integer)  # Reconstituted shelf life
    
    # Information
    primary_benefits = Column(Text)  # JSON or comma-separated
    contraindications = Column(Text)
    notes = Column(Text)
    research_links = Column(Text)  # URLs to studies

    # UI / assets
    image_filename = Column(String(255))  # e.g. 'bpc-157.png' stored under static/img/peptides/
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    vials = relationship("Vial", back_populates="peptide", cascade="all, delete-orphan")
    protocols = relationship("Protocol", back_populates="peptide")
    
    def __repr__(self):
        return f"<Peptide(name='{self.name}', common_name='{self.common_name}')>"


class Vial(Base):
    """Individual vial/bottle tracking"""
    __tablename__ = 'vials'
    
    id = Column(Integer, primary_key=True)
    peptide_id = Column(Integer, ForeignKey('peptides.id'), nullable=False)
    
    # Vial details
    mg_amount = Column(Float, nullable=False)  # Total mg in vial
    bacteriostatic_water_ml = Column(Float)  # How much BAC water added
    concentration_mcg_per_ml = Column(Float)  # Calculated concentration
    
    # Tracking
    purchase_date = Column(DateTime)
    reconstitution_date = Column(DateTime)
    expiration_date = Column(DateTime)
    lot_number = Column(String(50))
    vendor = Column(String(100))
    cost = Column(Float)
    
    # Status
    is_active = Column(Boolean, default=True)
    remaining_ml = Column(Float)  # Track how much is left
    
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    peptide = relationship("Peptide", back_populates="vials")
    injections = relationship("Injection", back_populates="vial")
    
    def calculate_concentration(self):
        """Calculate mcg per ml based on vial size and water added"""
        if self.mg_amount and self.bacteriostatic_water_ml:
            # Convert mg to mcg (1 mg = 1000 mcg)
            total_mcg = self.mg_amount * 1000
            self.concentration_mcg_per_ml = total_mcg / self.bacteriostatic_water_ml
            return self.concentration_mcg_per_ml
        return None
    
    def calculate_dose_volume(self, desired_dose_mcg):
        """Calculate ml needed for desired dose in mcg"""
        if self.concentration_mcg_per_ml:
            return desired_dose_mcg / self.concentration_mcg_per_ml
        return None
    
    def __repr__(self):
        return f"<Vial(peptide='{self.peptide.name if self.peptide else 'Unknown'}', mg={self.mg_amount})>"


class Protocol(Base):
    """Peptide protocol/cycle definition"""
    __tablename__ = 'protocols'
    
    id = Column(Integer, primary_key=True)
    peptide_id = Column(Integer, ForeignKey('peptides.id'), nullable=False)
    
    name = Column(String(200), nullable=False)  # e.g., "BPC-157 Injury Recovery"
    description = Column(Text)
    
    # Protocol parameters
    dose_mcg = Column(Float, nullable=False)
    frequency_per_day = Column(Integer, nullable=False)
    duration_days = Column(Integer)  # Total cycle length
    
    # Schedule
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    # Goals and tracking
    goals = Column(Text)  # What you're trying to achieve
    
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    peptide = relationship("Peptide", back_populates="protocols")
    injections = relationship("Injection", back_populates="protocol")
    
    def __repr__(self):
        return f"<Protocol(name='{self.name}', dose={self.dose_mcg}mcg)>"


class Injection(Base):
    """Individual injection log"""
    __tablename__ = 'injections'
    
    id = Column(Integer, primary_key=True)
    protocol_id = Column(Integer, ForeignKey('protocols.id'), nullable=False)
    vial_id = Column(Integer, ForeignKey('vials.id'), nullable=False)
    
    # Injection details
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    dose_mcg = Column(Float, nullable=False)
    volume_ml = Column(Float, nullable=False)
    injection_site = Column(String(100))  # e.g., "abdomen", "thigh"
    
    # Tracking
    side_effects = Column(Text)
    subjective_notes = Column(Text)  # How you felt, effects noticed
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    protocol = relationship("Protocol", back_populates="injections")
    vial = relationship("Vial", back_populates="injections")
    
    def __repr__(self):
        return f"<Injection(dose={self.dose_mcg}mcg, time={self.timestamp})>"


class ResearchNote(Base):
    """Store research, articles, and notes about peptides"""
    __tablename__ = 'research_notes'
    
    id = Column(Integer, primary_key=True)
    peptide_id = Column(Integer, ForeignKey('peptides.id'))
    
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    source_url = Column(String(1000))
    source_type = Column(String(50))  # "study", "article", "anecdote", "personal"
    
    # For AI/RAG - vector embeddings stored via pgvector
    # embedding = Column(Vector(1536))  # Will add pgvector support later
    
    tags = Column(String(500))  # Comma-separated tags
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<ResearchNote(title='{self.title[:50]}...')>"


# Database initialization functions
def create_database(db_url="postgresql://localhost/peptide_tracker"):
    """Create all tables in the database"""
    engine = create_engine(db_url, echo=True)
    Base.metadata.create_all(engine)
    return engine


def get_session(db_url="postgresql://localhost/peptide_tracker"):
    """Get a database session"""
    engine = create_engine(db_url, echo=False)
    Session = sessionmaker(bind=engine)
    return Session()


if __name__ == "__main__":
    # Create tables if running this file directly
    print("Creating database tables...")
    engine = create_database()
    print("Database tables created successfully!")
