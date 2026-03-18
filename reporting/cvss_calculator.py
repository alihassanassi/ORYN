"""
reporting/cvss_calculator.py — CVSS 3.1 base score calculation.

Pure calculation. No network. No LLM.

Usage:
    from reporting.cvss_calculator import calculate_cvss
    result = calculate_cvss('NETWORK', 'LOW', 'NONE', 'NONE', 'UNCHANGED', 'HIGH', 'NONE', 'NONE')
    # result: {'base_score': 7.5, 'vector_string': 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N', 'severity': 'HIGH'}
"""
from __future__ import annotations

# CVSS 3.1 metric weights per specification
_AV  = {'NETWORK': 0.85, 'ADJACENT': 0.62, 'LOCAL': 0.55, 'PHYSICAL': 0.20}
_AC  = {'LOW': 0.77,  'HIGH': 0.44}
_PR  = {
    'NONE':  {'UNCHANGED': 0.85, 'CHANGED': 0.85},
    'LOW':   {'UNCHANGED': 0.62, 'CHANGED': 0.68},
    'HIGH':  {'UNCHANGED': 0.27, 'CHANGED': 0.50},
}
_UI  = {'NONE': 0.85, 'REQUIRED': 0.62}
_CIA = {'NONE': 0.00, 'LOW': 0.22, 'HIGH': 0.56}

_AV_ABBR  = {'NETWORK': 'N', 'ADJACENT': 'A', 'LOCAL': 'L', 'PHYSICAL': 'P'}
_AC_ABBR  = {'LOW': 'L', 'HIGH': 'H'}
_PR_ABBR  = {'NONE': 'N', 'LOW': 'L', 'HIGH': 'H'}
_UI_ABBR  = {'NONE': 'N', 'REQUIRED': 'R'}
_S_ABBR   = {'UNCHANGED': 'U', 'CHANGED': 'C'}
_CIA_ABBR = {'NONE': 'N', 'LOW': 'L', 'HIGH': 'H'}


def _roundup(val: float) -> float:
    """CVSS 3.1 rounding: round up to 1 decimal place."""
    import math
    return math.ceil(val * 10) / 10


def calculate_cvss(
    attack_vector:        str,
    attack_complexity:    str,
    privileges_required:  str,
    user_interaction:     str,
    scope:                str,
    confidentiality:      str,
    integrity:            str,
    availability:         str,
) -> dict:
    """
    Calculate CVSS 3.1 base score.

    All parameters are uppercase strings matching CVSS 3.1 metric values.
    Returns dict with base_score (float), vector_string (str), severity (str).
    """
    # Normalise input
    AV = attack_vector.upper().strip()
    AC = attack_complexity.upper().strip()
    PR = privileges_required.upper().strip()
    UI = user_interaction.upper().strip()
    S  = scope.upper().strip()
    C  = confidentiality.upper().strip()
    I  = integrity.upper().strip()
    A  = availability.upper().strip()

    try:
        av_v = _AV[AV]
        ac_v = _AC[AC]
        pr_v = _PR[PR][S]
        ui_v = _UI[UI]
        c_v  = _CIA[C]
        i_v  = _CIA[I]
        a_v  = _CIA[A]
    except KeyError as e:
        return {'base_score': 0.0, 'vector_string': 'INVALID', 'severity': 'NONE', 'error': str(e)}

    # Exploitability sub-score
    exploitability = 8.22 * av_v * ac_v * pr_v * ui_v

    # Impact sub-score
    iss = 1 - (1 - c_v) * (1 - i_v) * (1 - a_v)
    if S == 'UNCHANGED':
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)

    if impact <= 0:
        base_score = 0.0
    elif S == 'UNCHANGED':
        base_score = _roundup(min(impact + exploitability, 10))
    else:
        base_score = _roundup(min(1.08 * (impact + exploitability), 10))

    # Severity rating
    if base_score == 0.0:
        severity = 'NONE'
    elif base_score < 4.0:
        severity = 'LOW'
    elif base_score < 7.0:
        severity = 'MEDIUM'
    elif base_score < 9.0:
        severity = 'HIGH'
    else:
        severity = 'CRITICAL'

    vector = (
        f"CVSS:3.1/AV:{_AV_ABBR[AV]}/AC:{_AC_ABBR[AC]}"
        f"/PR:{_PR_ABBR[PR]}/UI:{_UI_ABBR[UI]}"
        f"/S:{_S_ABBR[S]}/C:{_CIA_ABBR[C]}/I:{_CIA_ABBR[I]}/A:{_CIA_ABBR[A]}"
    )

    return {
        'base_score':    base_score,
        'vector_string': vector,
        'severity':      severity,
    }
