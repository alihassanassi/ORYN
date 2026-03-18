"""
tools/network_tools.py — Network intelligence tools for JARVIS.

All functions return strings (for direct display/TTS) or dicts (for structured use).
Network calls use stdlib only (urllib.request, socket, subprocess).
External tools (subfinder, httpx, nuclei) require separate installation.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import subprocess
import tempfile
import os
import urllib.request
import urllib.parse

try:
    from config import BLOCKED_COMMANDS
except Exception:
    BLOCKED_COMMANDS: list[str] = []

try:
    from security.rate_limiter import rate_limiter as _rate_limiter
except Exception:
    _rate_limiter = None  # type: ignore

logger = logging.getLogger(__name__)

# ── WMO weather codes (shared with morning_briefing) ──────────────────────────
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

# Default coordinates: San Diego, CA
_SD_LAT = 32.7157
_SD_LON = -117.1611


# ── 1. Weather ─────────────────────────────────────────────────────────────────

def tool_get_weather(location: str = "San Diego") -> str:
    """
    Fetch current weather for the given location using Open-Meteo (no API key).
    Returns a concise one-line weather summary.
    """
    loc = (location or "San Diego").strip()
    lat, lon = _SD_LAT, _SD_LON
    display_name = loc

    # Geocode non-default locations
    if loc.lower() not in ("san diego", ""):
        try:
            geo_url = (
                f"https://geocoding-api.open-meteo.com/v1/search"
                f"?name={urllib.parse.quote(loc)}&count=1"
            )
            req = urllib.request.Request(geo_url, headers={"User-Agent": "JARVIS/2.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                geo_data = json.loads(r.read())
            results = geo_data.get("results", [])
            if results:
                lat = results[0]["latitude"]
                lon = results[0]["longitude"]
                display_name = results[0].get("name", loc)
            else:
                return f"Location '{loc}' not found via geocoding."
        except Exception as exc:
            logger.debug("[weather] geocoding failed for %s: %s", loc, exc)
            return f"Geocoding failed for '{loc}': {exc}"

    # Fetch weather
    try:
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,weathercode,windspeed_10m"
            f"&temperature_unit=fahrenheit"
            f"&timezone=auto"
            f"&forecast_days=1"
        )
        req = urllib.request.Request(weather_url, headers={"User-Agent": "JARVIS/2.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read())

        current = data.get("current", {})
        temp    = current.get("temperature_2m")
        code    = current.get("weathercode", 0)
        wind    = current.get("windspeed_10m")

        condition = _WMO_CONDITIONS.get(code, _WMO_CONDITIONS.get((code // 10) * 10, "Clear"))
        temp_str  = f"{round(temp)}°F" if temp is not None else "N/A"
        wind_str  = f"Wind {round(wind)}mph." if wind is not None else ""

        return f"{display_name}: {condition}, {temp_str}. {wind_str}".strip()

    except Exception as exc:
        logger.debug("[weather] fetch failed: %s", exc)
        return f"Weather unavailable: {exc}"


# ── 2. DNS Lookup ──────────────────────────────────────────────────────────────

def tool_dns_lookup(domain: str) -> str:
    """
    Resolve A records for a domain using socket.getaddrinfo().
    Returns a formatted string with the resolved IPs or an error.
    """
    domain = (domain or "").strip()
    if not domain:
        return "No domain provided."
    if _rate_limiter is not None:
        if not _rate_limiter.check('dns_lookup', domain):
            return f"Rate limit reached for dns_lookup. Try again in an hour."
        _rate_limiter.record('dns_lookup', domain)
    try:
        infos = socket.getaddrinfo(domain, None)
        # Extract unique IPv4 addresses (AF_INET)
        ipv4 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET})
        # Extract unique IPv6 addresses (AF_INET6)
        ipv6 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET6})

        lines = [f"DNS: {domain}"]
        if ipv4:
            lines.append(f"  A:    {', '.join(ipv4)}")
        if ipv6:
            lines.append(f"  AAAA: {', '.join(ipv6)}")
        if not ipv4 and not ipv6:
            lines.append("  No records resolved.")
        return "\n".join(lines)
    except socket.gaierror as exc:
        return f"DNS lookup failed for '{domain}': {exc}"
    except Exception as exc:
        return f"DNS error: {exc}"


# ── 3. WHOIS Lookup ────────────────────────────────────────────────────────────

_CREDENTIAL_RE = re.compile(
    r"(password|passwd|secret|token|key)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


def _sanitize_whois(text: str) -> str:
    """Strip any credential-like strings from WHOIS output."""
    return _CREDENTIAL_RE.sub(r"\1: [REDACTED]", text)


def tool_whois_lookup(domain: str) -> str:
    """
    Retrieve WHOIS information for a domain.
    Tries python-whois library first; falls back to subprocess whois; then returns
    install instructions if neither is available.
    """
    domain = (domain or "").strip()
    if not domain:
        return "No domain provided."
    if _rate_limiter is not None:
        if not _rate_limiter.check('whois', domain):
            return f"Rate limit reached for whois. Try again in an hour."
        _rate_limiter.record('whois', domain)

    # Try python-whois
    try:
        import whois  # type: ignore
        w = whois.whois(domain)
        raw = str(w)
        raw = _sanitize_whois(raw)
        return raw[:500]
    except ImportError:
        pass
    except Exception as exc:
        return f"WHOIS lookup failed: {exc}"

    # Fallback: subprocess whois (Unix-like environments)
    if shutil.which("whois"):
        try:
            result = subprocess.run(
                ["whois", domain],
                capture_output=True, text=True, timeout=15
            )
            output = result.stdout or result.stderr
            lines  = output.splitlines()[:20]
            text   = _sanitize_whois("\n".join(lines))
            return text[:500] or f"No WHOIS data returned for '{domain}'."
        except Exception as exc:
            return f"WHOIS subprocess failed: {exc}"

    return (
        f"WHOIS unavailable. Install python-whois:\n"
        f"  pip install python-whois\n"
        f"Or on Linux/macOS: whois {domain}"
    )


# ── 4. Geolocate IP ────────────────────────────────────────────────────────────

_PRIVATE_IP_RE = re.compile(
    r"^("
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"127\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r")$"
)


def tool_geolocate_ip(ip: str) -> str:
    """
    Geolocate a public IP address using ip-api.com (free, no key, 45 req/min).
    Rejects private/loopback addresses.
    """
    ip = (ip or "").strip()
    if not ip:
        return "No IP address provided."

    if _PRIVATE_IP_RE.match(ip):
        return f"'{ip}' is a private/loopback address — geolocation not applicable."

    try:
        fields = "status,country,regionName,city,isp,org,query"
        url = f"http://ip-api.com/json/{urllib.parse.quote(ip)}?fields={fields}"
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/2.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())

        if data.get("status") != "success":
            return f"Geolocation failed for '{ip}': {data.get('message', 'unknown error')}"

        city    = data.get("city", "")
        region  = data.get("regionName", "")
        country = data.get("country", "")
        isp     = data.get("isp", "")
        org     = data.get("org", "")

        location_parts = [p for p in (city, region, country) if p]
        location_str   = ", ".join(location_parts) or "Unknown location"
        provider       = org if org and org != isp else isp

        return f"{ip} → {location_str} | ISP: {provider}"

    except Exception as exc:
        return f"Geolocation error: {exc}"


# ── 5. Clipboard ───────────────────────────────────────────────────────────────

def tool_get_clipboard() -> str:
    """
    Read the current clipboard contents.
    Tries pyperclip first; falls back to PowerShell on Windows.
    """
    # Try pyperclip
    try:
        import pyperclip  # type: ignore
        content = pyperclip.paste()
        if not content:
            return "Clipboard empty."
        return content[:500]
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("[clipboard] pyperclip failed: %s", exc)

    # Fallback: PowerShell
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5
        )
        content = result.stdout.strip()
        if not content:
            return "Clipboard empty."
        return content[:500]
    except Exception as exc:
        return f"Clipboard read failed: {exc}"


# ── 6. URL Analyze ─────────────────────────────────────────────────────────────

def tool_url_analyze(url: str) -> str:
    """
    Parse and analyze a URL — extract components and flag security concerns.
    """
    url = (url or "").strip()
    if not url:
        return "No URL provided."

    # Add scheme if missing for parsing
    parse_target = url if "://" in url else f"https://{url}"
    parsed = urllib.parse.urlparse(parse_target)

    lines = []

    # Protocol
    scheme = parsed.scheme or "https"
    lines.append(f"Protocol:  {scheme}")

    # Credentials in URL
    if parsed.username or parsed.password:
        lines.append(f"  WARNING: Credentials embedded in URL!")
        lines.append(f"  Username: {parsed.username}")
        if parsed.password:
            lines.append(f"  Password: [REDACTED]")

    # Host
    host = parsed.hostname or ""
    lines.append(f"Host:      {host}")

    # Is host an IP address?
    try:
        socket.inet_aton(host)
        lines.append(f"  NOTE: Host is an IP address (not a domain name)")
    except (socket.error, OSError):
        pass

    # Port
    default_ports = {"http": 80, "https": 443, "ftp": 21, "ssh": 22}
    default_port  = default_ports.get(scheme)
    if parsed.port:
        port_note = " (default)" if parsed.port == default_port else " (non-standard)"
        lines.append(f"Port:      {parsed.port}{port_note}")
    else:
        lines.append(f"Port:      {default_port or 'unspecified'} (default)")

    # Path
    if parsed.path and parsed.path != "/":
        lines.append(f"Path:      {parsed.path}")
    else:
        lines.append(f"Path:      / (root)")

    # Query parameters
    if parsed.query:
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        count  = len(params)
        lines.append(f"Query:     {parsed.query} ({count} param{'s' if count != 1 else ''})")
    else:
        lines.append(f"Query:     none")

    # Fragment
    if parsed.fragment:
        lines.append(f"Fragment:  {parsed.fragment}")

    # Security flags
    flags: list[str] = []
    if scheme == "http":
        flags.append("Unencrypted HTTP — credentials/data sent in cleartext")
    if parsed.port and parsed.port not in (80, 443, 8080, 8443, 21, 22):
        flags.append(f"Unusual port {parsed.port}")
    if flags:
        lines.append(f"Flags:")
        for f in flags:
            lines.append(f"  ! {f}")

    return "\n".join(lines)


# ── 7. Subfinder ───────────────────────────────────────────────────────────────

def _is_blocked(value: str) -> bool:
    """Check whether a string matches any blocked command pattern."""
    v = value.lower()
    return any(b.lower() in v for b in BLOCKED_COMMANDS)


def tool_run_subfinder(domain: str) -> str:
    """
    Run subfinder passive subdomain enumeration against a domain.
    Requires subfinder to be installed via: go install ...
    """
    domain = (domain or "").strip()
    if not domain:
        return "No domain provided."

    if _is_blocked(domain):
        return f"Domain '{domain}' matches a blocked pattern. Aborted."

    if _rate_limiter is not None:
        if not _rate_limiter.check('subfinder', domain):
            return f"Rate limit reached for subfinder. Try again in an hour."
        _rate_limiter.record('subfinder', domain)

    if not shutil.which("subfinder"):
        return (
            "subfinder not installed. Install with:\n"
            f"  go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest\n"
            f"Then run: subfinder -d {domain}"
        )

    try:
        result = subprocess.run(
            ["subfinder", "-d", domain, "-silent"],
            capture_output=True, text=True, timeout=120
        )
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        if not lines:
            return f"No subdomains found for {domain}"
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return f"subfinder timed out after 120s for {domain}"
    except Exception as exc:
        return f"subfinder error: {exc}"


# ── 8. HTTPX ───────────────────────────────────────────────────────────────────

def tool_run_httpx(targets: str) -> str:
    """
    Probe a list of domains/IPs for live HTTP(S) services using httpx.
    targets: newline-separated list of hosts, or a single host.
    Requires httpx: go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest
    """
    targets = (targets or "").strip()
    if not targets:
        return "No targets provided."

    if _rate_limiter is not None:
        _httpx_key = targets.splitlines()[0].strip()
        if not _rate_limiter.check('httpx', _httpx_key):
            return f"Rate limit reached for httpx. Try again in an hour."
        _rate_limiter.record('httpx', _httpx_key)

    if not shutil.which("httpx"):
        return (
            "httpx not installed. Install with:\n"
            "  go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest"
        )

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(targets)
            tmp = f.name

        result = subprocess.run(
            ["httpx", "-l", tmp, "-silent", "-status-code", "-title"],
            capture_output=True, text=True, timeout=180
        )
        output = result.stdout.strip()
        return output or "No live hosts found."
    except subprocess.TimeoutExpired:
        return "httpx timed out after 180s."
    except Exception as exc:
        return f"httpx error: {exc}"
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ── 9. Nuclei ──────────────────────────────────────────────────────────────────

_UNSAFE_NUCLEI_TAGS = {"intrusive", "dos", "bruteforce", "rce-active", "sqli-active"}


def tool_run_nuclei(
    targets: str,
    template_tags: str = "cves,exposed-panels,misconfigs",
) -> str:
    """
    Run nuclei vulnerability scanner against a list of targets.
    Automatically strips unsafe template tags (intrusive, dos, bruteforce, etc.).
    Requires nuclei: go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
    """
    targets = (targets or "").strip()
    if not targets:
        return "No targets provided."

    if _rate_limiter is not None:
        _nuclei_key = targets.splitlines()[0].strip()
        if not _rate_limiter.check('nuclei', _nuclei_key):
            return f"Rate limit reached for nuclei. Try again in an hour."
        _rate_limiter.record('nuclei', _nuclei_key)

    if not shutil.which("nuclei"):
        return (
            "nuclei not installed. Install with:\n"
            "  go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest"
        )

    # Strip unsafe tags
    safe_tags = ",".join(
        t.strip()
        for t in template_tags.split(",")
        if t.strip() and t.strip().lower() not in _UNSAFE_NUCLEI_TAGS
    )
    if not safe_tags:
        return "All requested template tags were blocked (unsafe). Use: cves, exposed-panels, misconfigs."

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(targets)
            tmp = f.name

        result = subprocess.run(
            ["nuclei", "-l", tmp, "-tags", safe_tags, "-silent", "-no-color"],
            capture_output=True, text=True, timeout=300
        )
        output = result.stdout.strip()
        return output or "No findings from nuclei scan."
    except subprocess.TimeoutExpired:
        return "nuclei timed out after 300s."
    except Exception as exc:
        return f"nuclei error: {exc}"
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ── 10. List Capabilities ──────────────────────────────────────────────────────

def tool_list_capabilities() -> str:
    """
    Return a formatted summary of all JARVIS tool capabilities,
    including install status of external recon tools.
    """
    def _installed(cmd: str) -> str:
        return "[installed]" if shutil.which(cmd) else "[requires go install]"

    lines = [
        "JARVIS Capabilities",
        "=" * 40,
        "",
        "Intelligence:",
        "  get_weather        — current weather for any location",
        "  dns_lookup         — resolve A/AAAA records for a domain",
        "  whois_lookup       — WHOIS registration info for a domain",
        "  geolocate_ip       — geolocation for a public IP address",
        "  url_analyze        — parse and security-audit a URL",
        "  get_clipboard      — read current clipboard contents",
        "",
        "Recon:",
        f"  run_subfinder      — passive subdomain enum  {_installed('subfinder')}",
        f"  run_httpx          — HTTP service probing     {_installed('httpx')}",
        f"  run_nuclei         — vulnerability scanning   {_installed('nuclei')}",
        "",
        "System:",
        "  system_status      — CPU, RAM, disk, network, uptime",
        "  cleanup_disk       — free temp/recycle space",
        "  run_command        — execute PowerShell command",
        "  open_app           — launch application by name",
        "",
        "Projects:",
        "  list_projects      — list all operator projects",
        "  switch_project     — activate a project",
        "  save_note          — save a note to current project",
        "  save_target        — save a recon target",
        "  save_finding       — save a security finding",
        "  list_targets       — list project targets",
        "  list_findings      — list project findings",
        "",
        "Bug Bounty Programs:",
        "  list_programs      — list all programs with scope and status",
        "  create_program     — create a program with scope domains",
        "  add_scope          — add a domain to a program's scope",
        "  program_status     — get status and finding counts",
        "  set_program_status — set program status (active/paused/completed)",
        "  scope_check        — verify if a domain is in scope for a program",
        "",
        "Findings & Reports:",
        "  finding_digest     — severity breakdown and top priorities",
        "  list_unverified_findings — findings awaiting review",
        "  verify_finding     — read-only verification of a finding",
        "  score_finding      — AI-powered bounty potential scoring",
        "  draft_report       — draft a HackerOne report for a finding",
        "",
        "Research:",
        "  research_digest    — recent CVE intelligence digest",
        "  search_research    — search stored research by keyword",
        "",
        "Strategy & Autonomy:",
        "  strategy_briefing  — current mission stage and next action",
        "  morning_briefing   — full operator morning briefing",
        "  recon_loop_start   — start autonomous recon loop",
        "  recon_loop_stop    — stop autonomous recon loop",
        "  recon_loop_status  — get recon loop status",
        "  kill_switch_trigger — emergency stop all autonomous ops",
        "  kill_switch_reset  — resume autonomous operations",
        "  watchdog_status    — health status of all services",
        "  preference_summary — tool approval statistics",
        "",
        "Voice:",
        "  list_voices        — list installed TTS voices",
        "  set_voice          — change speaking voice",
        "  list_voice_profiles — list Kokoro neural voice profiles",
        "  set_voice_profile  — switch active voice profile",
        "  switch_persona     — switch JARVIS persona (jarvis/india/ct7567/morgan)",
        "",
        "Admin:",
        "  token_stats        — local vs cloud LLM usage and cost",
        "  db_maintenance     — database stats, vacuum, prune",
    ]
    return "\n".join(lines)
