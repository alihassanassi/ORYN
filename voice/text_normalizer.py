"""voice/text_normalizer.py — Text normalization for TTS rendering of technical content.

Converts technical strings (CVEs, IPs, URLs, paths, hex, etc.) into forms
that produce clean spoken output. Does not over-normalize — only transforms
patterns that consistently sound bad when read raw by a TTS engine.

Normalization styles:
  cyber    — Full normalization, cyber/security operator context (default)
  military — Clipped, efficient rendering for military/tactical content
  standard — Minimal normalization for general conversation

Examples:
  CVE-2024-12345      → "CVE 2024 dash 12345"
  192.168.0.1         → "192 dot 168 dot 0 dot 1"
  :443                → "port 443"
  https://api.x.com/v1/login → "api.x.com, v1 slash login"
  /api/v1/login       → "slash api slash v1 slash login"
  0x1337              → "hex 1337"
  90%                 → "90 percent"
  ```code block```    → "code block"
"""
from __future__ import annotations

import re

# Words that must NEVER be spelled out as individual letters by the TTS engine.
# These are proper names, brand names, or technical terms whose uppercase form
# is already their correct pronunciation.
PROTECTED_WORDS: frozenset[str] = frozenset({
    "JARVIS", "J.A.R.V.I.S", "J.A.R.V.I.S.",
    "INDIA", "MORGAN",
    "SHODAN", "NUCLEI", "HTTPX", "NMAP",
    "CVE", "CVSS", "XSS", "IDOR", "SSRF", "RCE",
    "SQLI", "API", "URL", "HTML", "HTTP", "HTTPS",
})


class TextNormalizer:
    """Normalize text for TTS rendering of cybersecurity / operator content."""

    STYLE_CYBER    = "cyber"
    STYLE_MILITARY = "military"
    STYLE_STANDARD = "standard"

    def normalize(self, text: str, style: str = STYLE_CYBER) -> str:
        """Apply normalization pipeline. Returns TTS-ready text."""
        # Protect JARVIS pronunciation — it is a NAME not an acronym
        text = text.replace("J.A.R.V.I.S.", "JARVIS")
        text = text.replace("J.A.R.V.I.S", "JARVIS")
        text = self._strip_code_fences(text)
        text = self._strip_inline_code(text)
        text = self._strip_markdown(text)
        text = self._normalize_cves(text)
        text = self._normalize_ips(text)
        text = self._normalize_ports(text)
        text = self._normalize_urls(text)
        text = self._normalize_windows_paths(text)
        text = self._normalize_unix_paths(text)
        text = self._normalize_hex(text)
        text = self._normalize_bullets(text)
        text = self._normalize_timestamps(text)
        text = self._normalize_percentages(text)
        if style in (self.STYLE_CYBER, self.STYLE_MILITARY):
            text = self._normalize_cyber_abbreviations(text)
        text = self._clean_whitespace(text)
        return text

    def chunk(self, text: str, max_chars: int = 450) -> str:
        """Return a speakable chunk from text.

        Splits on sentence boundaries and returns the first max_chars worth.
        Used by the orchestrator to avoid speaking multi-paragraph responses verbatim.
        """
        if len(text) <= max_chars:
            return text
        sentences = re.split(r"(?<=[.!?])\s+", text)
        result: list[str] = []
        total = 0
        for s in sentences:
            if total + len(s) + 1 > max_chars and result:
                break
            result.append(s)
            total += len(s) + 1
        return " ".join(result) if result else text[:max_chars]

    # ── Step implementations ──────────────────────────────────────────────────

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Replace fenced code blocks (``` ... ```) with 'code block'."""
        text = re.sub(r"```[a-zA-Z]*\n[\s\S]*?```", "code block", text)
        text = re.sub(r"```[\s\S]*?```", "code block", text)
        return text

    @staticmethod
    def _strip_inline_code(text: str) -> str:
        """Remove inline code backticks; keep the content."""
        return re.sub(r"`([^`]*)`", r"\1", text)

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Strip common markdown syntax."""
        # Headers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Bold and italic
        text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
        # Horizontal rules
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # Table separator rows
        text = re.sub(r"\|[-: ]+\|[-: |]*", "", text)
        # Remaining pipe chars (table cells)
        text = re.sub(r"\|", " ", text)
        # Markdown links [text](url) → text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Markdown images → skip
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
        # Blockquote markers
        text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
        return text

    @staticmethod
    def _normalize_cves(text: str) -> str:
        """CVE-2024-12345 → 'CVE 2024 dash 12345'."""
        return re.sub(
            r"\bCVE-(\d{4})-(\d+)\b",
            lambda m: f"CVE {m.group(1)} dash {m.group(2)}",
            text,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _normalize_ips(text: str) -> str:
        """192.168.0.1 → '192 dot 168 dot 0 dot 1'."""
        def _ip_replace(m: re.Match) -> str:
            return " dot ".join(m.group(0).split("."))
        return re.sub(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
            _ip_replace,
            text,
        )

    @staticmethod
    def _normalize_ports(text: str) -> str:
        """Standalone :443 → 'port 443'. Avoids matching version numbers like 3.1."""
        return re.sub(
            r"(?<![.\d]):(\d{2,5})\b",
            lambda m: f"port {m.group(1)}",
            text,
        )

    @staticmethod
    def _normalize_urls(text: str) -> str:
        """https://api.example.com/v1/login → 'api.example.com, v1 slash login'."""
        def _url_replace(m: re.Match) -> str:
            url = m.group(0)
            # Strip scheme
            url = re.sub(r"^https?://", "", url)
            # Remove trailing punctuation that isn't part of the URL
            url = url.rstrip(".,;:!?)")
            parts = url.split("/", 1)
            domain = parts[0]
            path   = parts[1] if len(parts) > 1 else ""
            # Remove query string and fragment
            path = re.sub(r"[?#].*$", "", path)
            path_parts = [p for p in path.split("/") if p]
            if path_parts:
                return f"{domain}, {' slash '.join(path_parts)}"
            return domain
        return re.sub(r"https?://[^\s\)\]\"'<>]+", _url_replace, text)

    @staticmethod
    def _normalize_windows_paths(text: str) -> str:
        """C:\\path\\to\\file → 'C colon, backslash path backslash to backslash file'."""
        def _win_replace(m: re.Match) -> str:
            path = m.group(0)
            drive, _, rest = path.partition(":\\")
            rest_spoken = " backslash ".join(rest.split("\\"))
            return f"{drive} colon, backslash {rest_spoken}"
        return re.sub(r"[A-Za-z]:\\[^\s\"'<>]*", _win_replace, text)

    @staticmethod
    def _normalize_unix_paths(text: str) -> str:
        """Multi-component Unix paths: /api/v1/login → 'slash api slash v1 slash login'.
        Single-component paths (/bin, /etc) are left alone to avoid mangling prose.
        """
        def _unix_replace(m: re.Match) -> str:
            path = m.group(0)
            parts = [p for p in path.split("/") if p]
            if len(parts) < 2:
                return path
            return "slash " + " slash ".join(parts)
        return re.sub(r"(?<!\w)/[a-zA-Z0-9_.][a-zA-Z0-9_/.-]*(?=/[a-zA-Z0-9_])", _unix_replace, text)

    @staticmethod
    def _normalize_hex(text: str) -> str:
        """0x1337 → 'hex 1337'."""
        return re.sub(
            r"\b0x([0-9a-fA-F]+)\b",
            lambda m: f"hex {m.group(1)}",
            text,
        )

    @staticmethod
    def _normalize_bullets(text: str) -> str:
        """Strip bullet point markers; keep the text content."""
        text = re.sub(r"^\s*[-•*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
        return text

    @staticmethod
    def _normalize_timestamps(text: str) -> str:
        """ISO 8601 timestamps → natural spoken form."""
        _MONTHS = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        def _ts_replace(m: re.Match) -> str:
            year, month, day, hour, minute = (
                m.group(1), int(m.group(2)), m.group(3), m.group(4), m.group(5)
            )
            month_name = _MONTHS[month - 1] if 1 <= month <= 12 else str(month)
            return f"{day} {month_name} {year} at {hour} {minute}"
        return re.sub(
            r"\b(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?\b",
            _ts_replace,
            text,
        )

    @staticmethod
    def _normalize_percentages(text: str) -> str:
        """90% → '90 percent'."""
        return re.sub(r"(\d+(?:\.\d+)?)\s*%", r"\1 percent", text)

    @staticmethod
    def _normalize_cyber_abbreviations(text: str) -> str:
        """Expand selected cybersecurity abbreviations for clear TTS pronunciation.

        Any word whose uppercase form is in PROTECTED_WORDS is never expanded —
        it is a name or brand term whose all-caps form is the correct spoken form.
        """
        _ABBR: dict[str, str] = {
            r"\bSQLi\b": "SQL injection",
            r"\bXSS\b":  "cross-site scripting",
            r"\bSSRF\b": "server-side request forgery",
            r"\bRCE\b":  "remote code execution",
            r"\bLFI\b":  "local file inclusion",
            r"\bRFI\b":  "remote file inclusion",
            r"\bDoS\b":  "denial of service",
            r"\bDDoS\b": "distributed denial of service",
        }
        for pattern, replacement in _ABBR.items():
            # Extract the bare keyword from the \b-bounded pattern to check
            # whether it is in the protected set before substituting.
            bare = pattern.replace(r"\b", "")
            if bare.upper() in PROTECTED_WORDS:
                continue  # never expand protected words
            text = re.sub(pattern, replacement, text)
        return text

    @staticmethod
    def _clean_whitespace(text: str) -> str:
        """Collapse excess whitespace and newlines."""
        text = re.sub(r"\n{2,}", ". ", text)
        text = re.sub(r"\n",    ". ", text)
        text = re.sub(r"\s{2,}", " ", text)
        # Collapse repeated sentence-ending dots
        text = re.sub(r"\.(\s*\.)+", ".", text)
        return text.strip()
