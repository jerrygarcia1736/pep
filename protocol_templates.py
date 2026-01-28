"""Protocol templates for the free (beginner) experience.

These are EDUCATIONAL examples only — not medical advice.
"""

TEMPLATES = [
    {
        "slug": "bpc157-healing",
        "peptide_name": "BPC-157",
        "title": "BPC-157 Healing Protocol",
        "subtitle": "Body Protection Compound-157",
        "dose_mcg": 350.0,
        "frequency_per_day": 2,
        "duration_days": 42,
        "goals": "Recovery / soft tissue support",
        "route": "Subcutaneous injection",
        "header_color": "#198754",  # bootstrap success
        "icon": "bi bi-heart-pulse",
        "dosing": [
            {"label": "Dose", "value": "250–500 mcg"},
            {"label": "Frequency", "value": "1–2× per day"},
            {"label": "Duration", "value": "4–6 weeks"},
            {"label": "Route", "value": "Subcutaneous injection"},
        ],
        "benefits": [
            "Accelerated healing of muscles, tendons, and ligaments",
            "Gut health support",
            "Anti-inflammatory effects",
            "Joint and connective tissue repair",
        ],
    },
    {
        "slug": "tb500-recovery",
        "peptide_name": "TB-500",
        "title": "TB-500 Recovery Protocol",
        "subtitle": "Thymosin Beta-4",
        "dose_mcg": 2500.0,
        "frequency_per_day": 0,  # used as a label only; creation uses weekly-style approximation below
        "duration_days": 42,
        "goals": "Recovery / inflammation",
        "route": "Subcutaneous injection",
        "header_color": "#0dcaf0",  # bootstrap info
        "icon": "bi bi-shield-plus",
        "dosing": [
            {"label": "Loading Phase", "value": "2–5 mg, 2× per week"},
            {"label": "Maintenance", "value": "2–5 mg, 1× per week"},
            {"label": "Duration", "value": "4–6 weeks loading, then maintenance"},
            {"label": "Route", "value": "Subcutaneous injection"},
        ],
        "benefits": [
            "Promotes healing and tissue repair",
            "Reduces inflammation",
            "Improves flexibility and joint mobility",
            "Accelerates recovery from injuries",
        ],
    },
    {
        "slug": "ghkcu-skin",
        "peptide_name": "GHK-Cu",
        "title": "GHK-Cu Skin Protocol",
        "subtitle": "Copper Peptide",
        "dose_mcg": 2000.0,
        "frequency_per_day": 1,
        "duration_days": 56,
        "goals": "Skin / hair support",
        "route": "Subcutaneous injection",
        "header_color": "#ffc107",  # bootstrap warning
        "icon": "bi bi-droplet-half",
        "dosing": [
            {"label": "Dose", "value": "1–3 mg"},
            {"label": "Frequency", "value": "1× per day"},
            {"label": "Duration", "value": "6–8 weeks"},
            {"label": "Route", "value": "Subcutaneous injection (or topical per product)"},
        ],
        "benefits": [
            "Supports skin quality and collagen signaling (research)",
            "May support wound healing (research)",
            "Hair/scalp support (research)",
            "General tissue support (research)",
        ],
    },
    {
        "slug": "ipamorelin-sleep-recovery",
        "peptide_name": "Ipamorelin",
        "title": "Ipamorelin Sleep & Recovery Protocol",
        "subtitle": "Growth Hormone Secretagogue",
        "dose_mcg": 250.0,
        "frequency_per_day": 1,
        "duration_days": 56,
        "goals": "Recovery / sleep",
        "route": "Subcutaneous injection",
        "header_color": "#0d6efd",  # bootstrap primary
        "icon": "bi bi-moon-stars",
        "dosing": [
            {"label": "Dose", "value": "200–300 mcg"},
            {"label": "Frequency", "value": "1× per day (often evening)"},
            {"label": "Duration", "value": "6–8 weeks"},
            {"label": "Route", "value": "Subcutaneous injection"},
        ],
        "benefits": [
            "May support sleep quality (anecdotal / research context)",
            "Recovery support (research context)",
            "May support body composition goals (research context)",
        ],
    },
    {
        "slug": "cjc1295-sleep-recovery",
        "peptide_name": "CJC-1295",
        "title": "CJC-1295 Recovery Protocol",
        "subtitle": "Growth Hormone Releasing Hormone Analog",
        "dose_mcg": 200.0,
        "frequency_per_day": 1,
        "duration_days": 56,
        "goals": "Recovery / longevity",
        "route": "Subcutaneous injection",
        "header_color": "#6f42c1",  # purple
        "icon": "bi bi-activity",
        "dosing": [
            {"label": "Dose", "value": "100–300 mcg"},
            {"label": "Frequency", "value": "1× per day (or per clinician)"},
            {"label": "Duration", "value": "6–8 weeks"},
            {"label": "Route", "value": "Subcutaneous injection"},
        ],
        "benefits": [
            "May support recovery (research context)",
            "May support sleep quality (research context)",
            "Often discussed alongside GH secretagogues (research context)",
        ],
    },
    {
        "slug": "motsc-metabolic",
        "peptide_name": "MOTS-C",
        "title": "MOTS-C Metabolic Protocol",
        "subtitle": "Mitochondrial-Derived Peptide",
        "dose_mcg": 2500.0,
        "frequency_per_day": 0,
        "duration_days": 28,
        "goals": "Metabolic support",
        "route": "Subcutaneous injection",
        "header_color": "#20c997",  # teal
        "icon": "bi bi-lightning-charge",
        "dosing": [
            {"label": "Dose", "value": "2–5 mg"},
            {"label": "Frequency", "value": "2–3× per week"},
            {"label": "Duration", "value": "4 weeks (example)"},
            {"label": "Route", "value": "Subcutaneous injection"},
        ],
        "benefits": [
            "Metabolic support (research context)",
            "Energy / endurance support (research context)",
            "Discussed for mitochondrial signaling (research context)",
        ],
    },
]

TEMPLATE_BY_SLUG = {t["slug"]: t for t in TEMPLATES}
