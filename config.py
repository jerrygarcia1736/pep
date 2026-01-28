"""
Configuration for Peptide Tracker
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration"""
    
    # Database configuration
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "peptide_tracker")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    
    # Construct database URL
    DATABASE_URL = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    
    # Alternative: SQLite for local development (no Postgres needed)
    # DATABASE_URL = "sqlite:///peptide_tracker.db"
    
    # AI API Keys (for future use)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    
    # Application settings
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"
    
    @classmethod
    def get_database_url(cls, use_sqlite: bool = False) -> str:
        """Get database URL, optionally forcing SQLite"""
        if use_sqlite:
            return "sqlite:///peptide_tracker.db"
        return cls.DATABASE_URL
    
    @classmethod
    def print_config(cls):
        """Print current configuration (hiding sensitive data)"""
        print("\n" + "="*60)
        print("PEPTIDE TRACKER CONFIGURATION")
        print("="*60)
        print(f"Database: {cls.DB_NAME}")
        print(f"Host: {cls.DB_HOST}:{cls.DB_PORT}")
        print(f"User: {cls.DB_USER}")
        print(f"Password: {'*' * len(cls.DB_PASSWORD) if cls.DB_PASSWORD else 'Not set'}")
        print(f"Debug mode: {cls.DEBUG}")
        print(f"OpenAI API: {'Configured' if cls.OPENAI_API_KEY else 'Not configured'}")
        print(f"Anthropic API: {'Configured' if cls.ANTHROPIC_API_KEY else 'Not configured'}")
        print("="*60 + "\n")


if __name__ == "__main__":
    Config.print_config()
