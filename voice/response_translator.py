"""
voice/response_translator.py — Natural speech converter for tool output.

JARVIS doesn't read logs. JARVIS interprets results.

This translator sits between raw tool output and the LLM context,
converting machine output into natural language summaries that the
LLM can speak directly or build upon conversationally.

Output is persona-aware — the same finding is framed differently
for JARVIS vs Rex vs Morgan vs India.

Usage:
    from voice.response_translator import translate_tool_result
    natural = translate_tool_result('subfinder', result_dict, 'jarvis')
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)


def translate_tool_result(tool_name: str, result: dict,
                           persona: str = 'jarvis') -> str:
    """
    Convert a raw tool result dict into natural language.

    Parameters
    ----------
    tool_name : str
        The tool that was called (e.g. 'subfinder', 'nuclei').
    result : dict
        Tool result with keys: ok (bool), output (str), error (str), meta (dict).
    persona : str
        Active persona for framing the response.

    Returns
    -------
    str
        Natural language summary suitable for LLM ingestion or direct TTS.
    """
    ok     = result.get('ok', True)
    output = result.get('output', '') or ''
    error  = result.get('error', '') or ''
    meta   = result.get('meta', {}) or {}

    if not ok:
        return _translate_error(tool_name, error or output, persona)

    _translators = {
        'subfinder':       _translate_subfinder,
        'run_subfinder':   _translate_subfinder,
        'httpx':           _translate_httpx,
        'run_httpx':       _translate_httpx,
        'nuclei':          _translate_nuclei,
        'run_nuclei':      _translate_nuclei,
        'dnsx':            _translate_dns,
        'run_dnsx':        _translate_dns,
        'katana':          _translate_crawler,
        'run_katana':      _translate_crawler,
        'gau':             _translate_crawler,
        'run_gau':         _translate_crawler,
        'ffuf':            _translate_fuzzer,
        'run_ffuf':        _translate_fuzzer,
        'system_status':   _translate_system,
    }

    translator = _translators.get(tool_name, _translate_generic)
    try:
        return translator(output, meta, persona)
    except Exception as e:
        logger.debug("[Translator] error translating %s: %s", tool_name, e)
        return _translate_generic(output, meta, persona)


# ── Per-tool translators ───────────────────────────────────────────────────────

def _translate_subfinder(output: str, meta: dict, persona: str) -> str:
    lines = [l.strip() for l in output.strip().split('\n') if l.strip()]
    count = len(lines)
    if count == 0:
        return _zero_result(persona, 'subdomains')
    preview = ', '.join(lines[:3])
    more    = f" Plus {count - 3} more." if count > 3 else ""
    return {
        'jarvis':  f"{count} subdomain{'s' if count != 1 else ''} surfaced. Leading: {preview}.{more}",
        'ct7567':  f"{count} targets identified. Top: {preview}.{more}",
        'india':   f"Found {count} subdomains — the attack surface is taking shape. Starting with: {preview}.{more}",
        'morgan':  f"The surface widens. {count} subdomains emerged. Among them: {preview}.{more}",
    }.get(persona, f"{count} subdomains found: {preview}.{more}")


def _translate_httpx(output: str, meta: dict, persona: str) -> str:
    lines = [l for l in output.strip().split('\n') if l.strip()]
    live  = [l for l in lines if any(c in l for c in ['[200]','[301]','[302]','[403]','[401]','[500]'])]
    count = len(live) or len(lines)
    if count == 0:
        return _zero_result(persona, 'live hosts')
    interesting = next(
        (l for l in live if any(t in l.lower() for t in
         ['jenkins','admin','api','dev','stage','login','dashboard','portal'])),
        None
    )
    suffix = f" Notable: {interesting}." if interesting else ""
    return {
        'jarvis':  f"{count} host{'s' if count != 1 else ''} responding.{suffix}",
        'ct7567':  f"{count} live.{suffix}",
        'india':   f"{count} systems answered.{suffix}",
        'morgan':  f"{count} doors are open.{suffix}",
    }.get(persona, f"{count} hosts live.{suffix}")


def _translate_nuclei(output: str, meta: dict, persona: str) -> str:
    lines  = [l for l in output.strip().split('\n') if l.strip() and '[' in l]
    crits  = [l for l in lines if '[critical]' in l.lower()]
    highs  = [l for l in lines if '[high]' in l.lower()]
    mediums = [l for l in lines if '[medium]' in l.lower()]
    others  = len(lines) - len(crits) - len(highs) - len(mediums)
    if not lines:
        return _zero_result(persona, 'vulnerabilities')
    parts = []
    if crits:   parts.append(f"{len(crits)} critical")
    if highs:   parts.append(f"{len(highs)} high")
    if mediums: parts.append(f"{len(mediums)} medium")
    if others > 0: parts.append(f"{others} lower severity")
    summary = ", ".join(parts)
    top     = crits[0] if crits else highs[0] if highs else mediums[0] if mediums else lines[0]
    return {
        'jarvis':  f"Scan complete. {summary}. Top finding: {top[:120]}",
        'ct7567':  f"Contact. {summary}. Lead: {top[:100]}",
        'india':   f"The scanner found something — {summary}. Most notable: {top[:120]}",
        'morgan':  f"The vulnerabilities reveal themselves. {summary}. The one that stands out: {top[:120]}",
    }.get(persona, f"Nuclei: {summary}.")


def _translate_dns(output: str, meta: dict, persona: str) -> str:
    lines = [l for l in output.strip().split('\n') if l.strip()]
    n = len(lines)
    if n == 0:
        return _zero_result(persona, 'DNS records')
    return f"{n} DNS resolution{'s' if n != 1 else ''} confirmed."


def _translate_crawler(output: str, meta: dict, persona: str) -> str:
    lines = [l for l in output.strip().split('\n')
             if l.strip() and l.strip().startswith('http')]
    n = len(lines) or len([l for l in output.strip().split('\n') if l.strip()])
    if n == 0:
        return _zero_result(persona, 'endpoints')
    return {
        'jarvis':  f"{n} endpoint{'s' if n != 1 else ''} crawled.",
        'ct7567':  f"{n} endpoints mapped.",
        'india':   f"Mapped {n} endpoints — the application topology is clearer now.",
        'morgan':  f"{n} paths through the system, each one a story.",
    }.get(persona, f"{n} endpoints crawled.")


def _translate_fuzzer(output: str, meta: dict, persona: str) -> str:
    lines = [l for l in output.strip().split('\n') if l.strip() and 'Status:' in l]
    interesting = [l for l in lines if any(c in l for c in ['200','301','302','403'])]
    n = len(interesting) or len(lines)
    if n == 0:
        return _zero_result(persona, 'fuzzer results')
    return {
        'jarvis':  f"{n} interesting path{'s' if n != 1 else ''} found during fuzzing.",
        'ct7567':  f"{n} hits. Check the list.",
        'india':   f"Fuzzing yielded {n} response{'s' if n != 1 else ''} worth investigating.",
        'morgan':  f"{n} hidden path{'s' if n != 1 else ''} — the fuzzer found what wasn't meant to be found.",
    }.get(persona, f"{n} fuzzer hits.")


def _translate_system(output: str, meta: dict, persona: str) -> str:
    # system_status output is already human-readable — just trim it
    lines = [l for l in output.strip().split('\n') if l.strip()]
    if not lines:
        return "System status unavailable."
    # Extract key metrics if present
    cpu_line = next((l for l in lines if 'cpu' in l.lower()), None)
    ram_line = next((l for l in lines if 'ram' in l.lower() or 'memory' in l.lower()), None)
    if cpu_line and ram_line:
        return {
            'jarvis':  f"Systems nominal. {cpu_line.strip()}. {ram_line.strip()}.",
            'ct7567':  f"Status: {cpu_line.strip()}. {ram_line.strip()}.",
            'india':   f"Everything looks healthy. {cpu_line.strip()}. {ram_line.strip()}.",
            'morgan':  f"The machine hums along. {cpu_line.strip()}.",
        }.get(persona, f"{cpu_line.strip()}. {ram_line.strip()}.")
    return lines[0][:200]


def _translate_generic(output: str, meta: dict, persona: str) -> str:
    lines = [l for l in output.strip().split('\n') if l.strip()]
    if not lines:
        return "Complete. No output."
    n = len(lines)
    preview = lines[0][:120]
    return (f"{n} result{'s' if n != 1 else ''}: {preview}"
            if n > 1 else preview)


def _translate_error(tool: str, error: str, persona: str) -> str:
    short = (error or "Unknown error")[:100]
    return {
        'jarvis':  f"That didn't go as planned. {short}",
        'ct7567':  f"Tool failure. {short}. Checking alternatives.",
        'india':   f"We hit a snag — {short}. Let me think about this.",
        'morgan':  f"Sometimes the path is blocked. {short}",
    }.get(persona, f"Error in tool: {short}")


def _zero_result(persona: str, thing: str) -> str:
    return {
        'jarvis':  f"No {thing} found. Clean result.",
        'ct7567':  f"Zero {thing}. Area clear.",
        'india':   f"Nothing found yet. The search continues.",
        'morgan':  f"Silence. No {thing} emerged.",
    }.get(persona, f"No {thing} found.")
