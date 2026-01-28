"""Seed a small set of FREE 'Example Starter Protocols'.

These are educational templates only (not medical advice).
Safe to run on every deploy: it will not duplicate templates.
"""

from sqlalchemy import and_
from models import Peptide, ProtocolTemplate


def seed_protocol_templates(session):
    # Find peptides by common names in your DB
    bpc = session.query(Peptide).filter(Peptide.name.ilike('%BPC-157%')).first()
    ghk = session.query(Peptide).filter(Peptide.name.ilike('%GHK%')).first()

    templates = []

    if bpc:
        templates.append(dict(
            peptide_id=bpc.id,
            name="BPC-157 – Recovery & Gut (Example)",
            description=(
                "Educational example starter protocol based on commonly discussed research use. "
                "Not medical advice."
            ),
            dose_mcg=250.0,
            frequency_per_day=1,
            duration_days=28,
            goals="Recovery, Gut",
            is_free=True,
        ))

    if ghk:
        templates.append(dict(
            peptide_id=ghk.id,
            name="GHK-Cu – Skin & Regeneration (Example)",
            description=(
                "Educational example starter protocol based on commonly discussed research use. "
                "Not medical advice."
            ),
            dose_mcg=150.0,
            frequency_per_day=1,
            duration_days=42,
            goals="Skin, Longevity",
            is_free=True,
        ))

    # Idempotent upsert: avoid duplicates by (peptide_id, name)
    created = 0
    for t in templates:
        exists = session.query(ProtocolTemplate).filter(
            and_(ProtocolTemplate.peptide_id == t["peptide_id"],
                 ProtocolTemplate.name == t["name"])
        ).first()
        if exists:
            exists.description = t["description"]
            exists.dose_mcg = t["dose_mcg"]
            exists.frequency_per_day = t["frequency_per_day"]
            exists.duration_days = t["duration_days"]
            exists.goals = t["goals"]
            exists.is_free = t["is_free"]
        else:
            session.add(ProtocolTemplate(**t))
            created += 1

    session.commit()
    return created
