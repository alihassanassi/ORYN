"""
scheduler/morning_briefing.py — JARVIS morning briefing generator.

Produces a natural-speech briefing covering:
  1. Human opener  — greeting, date, time, San Diego weather
  2. Overnight intel — new subdomains, findings queued for review
  3. Today's focus — most active program, one tactical suggestion
  4. Sign-off      — persona-specific closing line

Callable on-demand via the 'morning_briefing' tool:
  "JARVIS give me my morning briefing"

Weather: Open-Meteo API (free, no key needed, San Diego lat/lon hardcoded).
Timezone: America/Los_Angeles (San Diego).

NOTE: pytz is optional — stdlib datetime.timezone is used as fallback.
"""
from __future__ import annotations

import logging
import urllib.request
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# San Diego coordinates
_SD_LAT =  32.7157
_SD_LON = -117.1611

# WMO weather code → English description
_WMO_CONDITIONS: dict[int, str] = {
    0:  "Clear",
    1:  "Mainly clear",
    2:  "Partly cloudy",
    3:  "Overcast",
    45: "Foggy",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    80: "Showers",
    81: "Heavy showers",
    95: "Thunderstorm",
    99: "Thunderstorm with hail",
}


# ── Weather ────────────────────────────────────────────────────────────────────

def _get_weather(lat: float = _SD_LAT, lon: float = _SD_LON) -> dict:
    """
    Fetch current weather for San Diego from Open-Meteo (free, no API key).
    Returns: {'temp_f': int|None, 'condition': str, 'forecast': str}
    """
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,weathercode,windspeed_10m"
            f"&hourly=precipitation_probability"
            f"&temperature_unit=fahrenheit"
            f"&timezone=America%2FLos_Angeles"
            f"&forecast_days=1"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/2.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read())

        current   = data.get("current", {})
        temp      = current.get("temperature_2m")
        code      = current.get("weathercode", 0)
        condition = _WMO_CONDITIONS.get(code, _WMO_CONDITIONS.get((code // 10) * 10, "Clear"))

        # Afternoon rain probability (hours 12–18)
        hourly    = data.get("hourly", {})
        prec_prob = hourly.get("precipitation_probability", [0] * 24)
        pm_rain   = any(p > 60 for p in prec_prob[12:18])
        forecast  = "Rain likely this afternoon." if pm_rain else ""

        return {
            "temp_f":    round(temp) if temp is not None else None,
            "condition": condition,
            "forecast":  forecast,
        }
    except Exception as exc:
        logger.debug("[Briefing] weather fetch failed: %s", exc)
        return {"temp_f": None, "condition": "Unknown", "forecast": ""}


# ── Time / Greeting ────────────────────────────────────────────────────────────

def _get_time_greeting() -> tuple[str, str, str]:
    """
    Returns (greeting, time_str, date_str) for San Diego local time.
    Tries pytz first, falls back to UTC-8 (PST) / UTC-7 (PDT) approximation.
    """
    try:
        import pytz
        tz  = pytz.timezone("America/Los_Angeles")
        now = datetime.now(tz)
    except ImportError:
        # Rough fallback: detect DST manually (second Sunday in March through
        # first Sunday in November). Close enough for a greeting.
        utc_now = datetime.now(timezone.utc)
        # Simple offset: PDT=UTC-7 Mar–Nov, PST=UTC-8 Nov–Mar
        month = utc_now.month
        offset_h = -7 if 3 <= month <= 10 else -8
        now = utc_now + timedelta(hours=offset_h)

    hour = now.hour
    if 5 <= hour < 12:
        greeting = "Good morning"
    elif 12 <= hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    # "7:42 AM" — handle platforms without %-I
    try:
        time_str = now.strftime("%-I:%M %p")
    except ValueError:
        time_str = now.strftime("%I:%M %p").lstrip("0")

    # "Monday, March 16"
    try:
        date_str = now.strftime("%A, %B %-d")
    except ValueError:
        date_str = now.strftime("%A, %B %d").replace(" 0", " ")

    return greeting, time_str, date_str


# ── Overnight intelligence ─────────────────────────────────────────────────────

def _get_overnight_intel() -> dict:
    """
    Query the DB for activity since midnight local time.
    Returns counts for subdomains, findings, and the top active program.
    """
    result = {
        "new_subdomains": 0,
        "new_findings":   0,
        "top_severity":   "medium",
        "top_program":    None,
    }
    try:
        from storage.db import get_db
        with get_db() as conn:
            # New findings since midnight
            row = conn.execute("""
                SELECT COUNT(*) FROM scan_targets
                WHERE created_at >= date('now', 'localtime')
            """).fetchone()
            result["new_subdomains"] = row[0] if row else 0

            # Queued findings
            try:
                row2 = conn.execute("""
                    SELECT COUNT(*), MAX(severity) FROM findings
                    WHERE created_at >= date('now', '-1 day')
                """).fetchone()
                if row2 and row2[0]:
                    result["new_findings"] = row2[0]
                    result["top_severity"] = row2[1] or "medium"
            except Exception:
                pass  # findings table may not exist yet

            # Most active project
            try:
                row3 = conn.execute("""
                    SELECT project, COUNT(*) as c FROM messages
                    WHERE ts >= date('now', '-7 days')
                    GROUP BY project ORDER BY c DESC LIMIT 1
                """).fetchone()
                if row3:
                    result["top_program"] = row3[0]
            except Exception:
                pass

    except Exception as exc:
        logger.debug("[Briefing] intel query failed: %s", exc)

    return result


# ── Persona sign-offs ──────────────────────────────────────────────────────────

_SIGNOFFS: dict[str, str] = {
    "jarvis":  "I'll be monitoring. Say 'JARVIS' when you're ready.",
    "india":   "I'm here when you need me. Good hunting.",
    "ct7567":  "Standing by. Your call, Commander.",
    "morgan":  "The day is yours. Take your time.",
}


# ── Main briefing generator ────────────────────────────────────────────────────

def generate_briefing_text(persona: str = "jarvis") -> str:
    """
    Generate full morning briefing text, suitable for TTS.
    Callable on-demand at any time of day.

    Parameters
    ----------
    persona : str
        Active persona name ('jarvis', 'india', 'ct7567', 'morgan').

    Returns
    -------
    str
        Natural speech paragraph.
    """
    greeting, time_str, date_str = _get_time_greeting()
    weather = _get_weather()
    intel   = _get_overnight_intel()

    # Weather line
    if weather["temp_f"] is not None:
        weather_line = f"{weather['condition']}, {weather['temp_f']}°F"
    else:
        weather_line = weather["condition"]
    if weather.get("forecast"):
        weather_line += f". {weather['forecast']}"

    lines: list[str] = [
        f"{greeting}. It is {date_str}. The time is {time_str}.",
        f"San Diego: {weather_line}.",
    ]

    # Intelligence
    if intel["new_subdomains"] > 0:
        n = intel["new_subdomains"]
        lines.append(
            f"{n} new entr{'ies' if n != 1 else 'y'} recorded overnight."
        )

    if intel["new_findings"] > 0:
        n   = intel["new_findings"]
        sev = intel["top_severity"] or "medium"
        lines.append(
            f"{n} finding{'s' if n != 1 else ''} waiting for your review. "
            f"Highest severity: {sev}."
        )

    if intel["top_program"]:
        lines.append(f"Most active program: {intel['top_program']}.")

    if not intel["new_subdomains"] and not intel["new_findings"]:
        lines.append("Quiet overnight. No new discoveries to report.")

    # Strategy context
    try:
        from autonomy.strategy import StrategyEngine
        _eng = StrategyEngine()
        _state = _eng.get_current_mission()
        if _state and _state.target:
            lines.append(
                f"Active target: {_state.target}. "
                f"Stage: {_state.stage.value.replace('_', ' ')}. "
                f"{_eng.recommend_next_action(_state)}"
            )
    except Exception:
        pass  # strategy engine optional

    lines.append(_SIGNOFFS.get(persona, _SIGNOFFS["jarvis"]))

    return " ".join(lines)


# ── Tool-callable wrapper ──────────────────────────────────────────────────────

def tool_morning_briefing() -> str:
    """Tool entry point — dispatched from tools/registry.py."""
    try:
        import config as _cfg
        persona = getattr(_cfg, "ACTIVE_PERSONA", "jarvis")
        return generate_briefing_text(persona)
    except Exception as exc:
        logger.error("[Briefing] generation error: %s", exc)
        return "Unable to generate briefing at this time."
