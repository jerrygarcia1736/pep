"""
Injection Confidence Scoring
---------------------------
Purpose: Data-alignment / verification confidence (NOT medical safety).
Returns: score 0-100, band, and human-readable reasons.

Designed to be:
- transparent
- configurable thresholds
- safe language ("confidence", "alignment", "verification")

Used by:
- /api/injection-confidence (POST) to score an injection payload
- future: injection logging pipeline

Author: PeptideTracker.ai
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ConfidenceConfig:
    # weights (max contribution)
    protocol_weight: int = 30
    syringe_weight: int = 35
    reconstitution_weight: int = 20
    timing_weight: int = 10

    # protocol tolerances
    protocol_exact_pct: float = 0.02
    protocol_good_pct: float = 0.05
    protocol_ok_pct: float = 0.10

    # reconstitution tolerances
    bac_tolerance_ml: float = 0.2  # allow small syringe reading drift
    conc_minor_pct: float = 0.03   # 3% rounding
    conc_ok_pct: float = 0.08      # 8% mismatch

    # timing tolerance (fraction of interval)
    timing_good_frac: float = 0.20  # ±20% of expected interval

    # score bands
    band_high: int = 85
    band_medium: int = 65


def _pct_diff(a: float, b: float) -> float:
    if b == 0:
        return 1.0 if a != 0 else 0.0
    return abs(a - b) / abs(b)


def _clamp(n: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, n))


def compute_injection_confidence(payload: Dict[str, Any], cfg: ConfidenceConfig = ConfidenceConfig()) -> Dict[str, Any]:
    """
    Payload fields (all optional; missing fields are treated as 'unknown' = neutral):
      dose_mcg: float
      protocol_dose_mcg: float
      has_active_protocol: bool
      syringe:
        camera_used: bool
        snap_success: bool
        low_contrast: bool
        verification_skipped: bool
        manual_confirmed: bool
        syringe_type_used: "1ml"|"3ml"|...
        syringe_type_expected: "1ml"|"3ml"|...
      reconstitution:
        bac_ml_expected: float
        bac_ml_used: float
        concentration_expected: float   (mcg/ml or mg/ml — consistent units!)
        concentration_used: float
      timing:
        expected_interval_hours: float
        last_injection_at_iso: str (ISO)
        injection_at_iso: str (ISO)
      certainty:
        manual_dose_edit: bool
        warning_overridden: bool
        pep_ai_confirmed: bool
    """

    score = 100.0
    reasons: List[str] = []
    debug: Dict[str, Any] = {"components": {}}

    # -----------------
    # 1) Protocol match
    # -----------------
    dose = payload.get("dose_mcg")
    proto = payload.get("protocol_dose_mcg")
    has_proto = payload.get("has_active_protocol")
    proto_points = 0.0

    if has_proto is False or proto in (None, "", 0) or dose in (None, ""):
        proto_points = 0.0
        reasons.append("Protocol match: not scored (missing protocol or dose).")
    else:
        try:
            dose_f = float(dose)
            proto_f = float(proto)
            d = _pct_diff(dose_f, proto_f)
            if d <= cfg.protocol_exact_pct:
                proto_points = cfg.protocol_weight
                reasons.append("Protocol match: dose aligns closely with your protocol.")
            elif d <= cfg.protocol_good_pct:
                proto_points = cfg.protocol_weight * (25/30)
                reasons.append("Protocol match: dose is within the protocol tolerance.")
            elif d <= cfg.protocol_ok_pct:
                proto_points = cfg.protocol_weight * (15/30)
                reasons.append("Protocol match: dose is slightly outside the preferred range.")
            else:
                # penalty for large mismatch
                proto_points = -15.0
                reasons.append("Protocol match: dose appears off relative to your protocol.")
        except Exception:
            proto_points = 0.0
            reasons.append("Protocol match: not scored (invalid numbers).")

    score = score - cfg.protocol_weight + max(0.0, proto_points)  # normalize to weight
    if proto_points < 0:
        score += proto_points  # apply penalty
    debug["components"]["protocol"] = proto_points

    # -----------------------
    # 2) Syringe verification
    # -----------------------
    syr = payload.get("syringe") or {}
    camera_used = bool(syr.get("camera_used"))
    snap_success = bool(syr.get("snap_success"))
    low_contrast = bool(syr.get("low_contrast"))
    verification_skipped = bool(syr.get("verification_skipped"))
    manual_confirmed = bool(syr.get("manual_confirmed"))
    syringe_points = 0.0

    if verification_skipped:
        syringe_points = 0.0
        reasons.append("Syringe verification: skipped.")
    elif camera_used and snap_success and not low_contrast:
        syringe_points = cfg.syringe_weight
        reasons.append("Syringe verification: camera + snap confirmed plunger position.")
    elif camera_used and snap_success and low_contrast:
        syringe_points = cfg.syringe_weight * (15/35)
        reasons.append("Syringe verification: snap succeeded, but image contrast was low.")
    elif camera_used and not snap_success:
        syringe_points = cfg.syringe_weight * (25/35)
        reasons.append("Syringe verification: camera used (no snap).")
    elif manual_confirmed:
        syringe_points = 5.0
        reasons.append("Syringe verification: manually confirmed.")
    else:
        syringe_points = 0.0
        reasons.append("Syringe verification: not provided.")

    # syringe type check (bonus/penalty)
    used = (syr.get("syringe_type_used") or "").lower().strip()
    expected = (syr.get("syringe_type_expected") or "").lower().strip()
    type_bonus = 0.0
    if used and expected:
        if used == expected:
            type_bonus = 5.0
            reasons.append("Syringe type: matches the expected syringe.")
        else:
            type_bonus = -10.0
            reasons.append("Syringe type: does not match the expected syringe.")
    debug["components"]["syringe"] = syringe_points + type_bonus

    score = score - cfg.syringe_weight + max(0.0, syringe_points) + type_bonus

    # ----------------------------
    # 3) Reconstitution consistency
    # ----------------------------
    rec = payload.get("reconstitution") or {}
    rec_points = 0.0

    # BAC amount
    bac_exp = rec.get("bac_ml_expected")
    bac_used = rec.get("bac_ml_used")
    bac_points = 0.0
    if bac_exp is not None and bac_used is not None:
        try:
            b1 = float(bac_exp)
            b2 = float(bac_used)
            if abs(b1 - b2) <= cfg.bac_tolerance_ml:
                bac_points = 10.0
                reasons.append("Reconstitution: BAC water amount matches your plan.")
            elif abs(b1 - b2) <= (cfg.bac_tolerance_ml * 2):
                bac_points = 5.0
                reasons.append("Reconstitution: BAC water amount is close to your plan.")
            else:
                bac_points = -10.0
                reasons.append("Reconstitution: BAC water amount appears inconsistent with your plan.")
        except Exception:
            bac_points = 0.0
            reasons.append("Reconstitution: BAC check not scored (invalid numbers).")

    # Concentration check
    c_exp = rec.get("concentration_expected")
    c_used = rec.get("concentration_used")
    conc_points = 0.0
    if c_exp is not None and c_used is not None:
        try:
            c1 = float(c_exp)
            c2 = float(c_used)
            d = _pct_diff(c2, c1)
            if d <= cfg.conc_minor_pct:
                conc_points = 10.0
                reasons.append("Reconstitution: concentration aligns with your expected mix.")
            elif d <= cfg.conc_ok_pct:
                conc_points = 5.0
                reasons.append("Reconstitution: concentration is close (minor rounding/mismatch).")
            else:
                conc_points = -15.0
                reasons.append("Reconstitution: concentration looks inconsistent with your expected mix.")
        except Exception:
            conc_points = 0.0
            reasons.append("Reconstitution: concentration not scored (invalid numbers).")

    rec_points = bac_points + conc_points
    debug["components"]["reconstitution"] = rec_points

    score = score - cfg.reconstitution_weight + max(0.0, min(cfg.reconstitution_weight, bac_points + max(0.0, conc_points)))  # reward
    if bac_points < 0:
        score += bac_points
    if conc_points < 0:
        score += conc_points

    # -------------------
    # 4) Timing / schedule
    # -------------------
    timing = payload.get("timing") or {}
    timing_points = 0.0
    interval_h = timing.get("expected_interval_hours")
    last_iso = timing.get("last_injection_at_iso")
    inj_iso = timing.get("injection_at_iso")

    if interval_h and last_iso and inj_iso:
        try:
            interval_h = float(interval_h)
            last_dt = datetime.fromisoformat(str(last_iso).replace("Z", "+00:00"))
            inj_dt = datetime.fromisoformat(str(inj_iso).replace("Z", "+00:00"))
            delta_h = abs((inj_dt - last_dt).total_seconds()) / 3600.0
            frac = abs(delta_h - interval_h) / interval_h if interval_h else 0.0

            if frac <= cfg.timing_good_frac:
                timing_points = cfg.timing_weight
                reasons.append("Timing: aligns with your expected schedule.")
            elif frac <= (cfg.timing_good_frac * 2):
                timing_points = cfg.timing_weight * 0.5
                reasons.append("Timing: slightly off schedule.")
            else:
                timing_points = -5.0
                reasons.append("Timing: notably off schedule.")
        except Exception:
            timing_points = 0.0
            reasons.append("Timing: not scored (invalid timestamps).")
    else:
        timing_points = 0.0
        reasons.append("Timing: not scored (missing schedule context).")

    debug["components"]["timing"] = timing_points
    score = score - cfg.timing_weight + max(0.0, timing_points)
    if timing_points < 0:
        score += timing_points

    # -------------------------
    # 5) Certainty / Overrides
    # -------------------------
    cert = payload.get("certainty") or {}
    certainty_points = 0.0

    if cert.get("manual_dose_edit"):
        certainty_points -= 5.0
        reasons.append("Certainty: dose was manually edited.")
    if cert.get("warning_overridden"):
        certainty_points -= 10.0
        reasons.append("Certainty: warning was overridden.")
    if cert.get("pep_ai_confirmed"):
        certainty_points += 5.0
        reasons.append("Certainty: Pep AI confirmation used.")

    debug["components"]["certainty"] = certainty_points
    score += certainty_points

    # finalize
    score = float(_clamp(score, 0.0, 100.0))
    if score >= cfg.band_high:
        band = "high"
    elif score >= cfg.band_medium:
        band = "medium"
    else:
        band = "low"

    return {
        "score": round(score, 1),
        "band": band,
        "reasons": reasons,
        "debug": debug,  # can hide in UI; useful for tuning
    }
