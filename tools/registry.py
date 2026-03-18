"""
tools/registry.py — Tool schema list and central dispatch router.

TOOL_SCHEMAS is the list passed to the LLM.
dispatch() routes tool calls to their implementations.
"""
from __future__ import annotations
import logging as _logging

from tools.system_tools  import tool_system_status, tool_cleanup_disk, tool_self_reflect
from tools.shell_tools   import tool_run_command, tool_open_app
from tools.project_tools import (tool_list_projects, tool_switch_project,
                                  tool_save_note, tool_read_notes,
                                  tool_save_target, tool_list_targets,
                                  tool_save_finding, tool_list_findings)
from tools.voice_tools   import (tool_list_voices, tool_set_voice,
                                  tool_list_voice_profiles, tool_set_voice_profile,
                                  tool_switch_persona)
from tools.report_tools  import (tool_draft_report, tool_verify_finding,
                                  tool_score_finding, tool_finding_digest,
                                  tool_list_unverified_findings)
from tools.network_tools import (
    tool_get_weather, tool_dns_lookup, tool_whois_lookup,
    tool_geolocate_ip, tool_get_clipboard, tool_url_analyze,
    tool_run_subfinder, tool_run_httpx, tool_run_nuclei,
    tool_list_capabilities,
)
from tools.program_tools import (
    tool_list_programs, tool_create_program,
    tool_add_scope, tool_program_status, tool_set_program_status,
    tool_scope_check,
)
from voice.clip_manager import (
    tool_list_clips, tool_add_clip, tool_remove_clip, tool_validate_clip,
)
from security.sanitizer import validate_domain, validate_url
from tools.vision_tools import (
    _vision_status, _vision_list_known_people,
    _vision_rename_person, _vision_delete_all_faces,
)

# Memory subsystem tools — imported lazily to avoid hard dependency at load time
try:
    from memory.tools import (
        tool_remember, tool_recall, tool_forget, tool_pin_memory,
        tool_inspect_memory, tool_memory_stats, tool_memory_hygiene,
    )
    _MEMORY_AVAILABLE = True
except Exception:
    _MEMORY_AVAILABLE = False

# Convenience dict for FINAL 7 check — registry of all dispatchable tool names
REGISTRY: dict[str, callable] = {}

# ── Schemas exposed to the LLM ────────────────────────────────────────────────
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name":        "system_status",
            "description": "Get live system status: CPU, RAM, disk, uptime, network interfaces.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "self_reflect",
            "description": (
                "JARVIS reflects on his own capabilities and limitations. "
                "Use when the operator asks 'what can you do', 'what can't you do', "
                "'what are your capabilities', 'what are your limitations'."
            ),
            "parameters":  {
                "type":       "object",
                "properties": {
                    "aspect": {
                        "type":        "string",
                        "description": "What to reflect on: 'capabilities' or 'limitations'"
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "run_command",
            "description": "Execute a shell command via PowerShell. Approved commands run immediately. Unknown commands require operator confirmation.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "command":   {"type": "string",  "description": "The PowerShell command to run"},
                    "confirmed": {"type": "boolean", "description": "True if operator has confirmed execution"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "open_app",
            "description": "Open an application. Known apps: terminal, browser, chrome, vscode, code, wireshark, burpsuite, burp, notepad, explorer, powershell.",
            "parameters":  {
                "type":       "object",
                "properties": {"app": {"type": "string", "description": "App name to open"}},
                "required":   ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "list_projects",
            "description": "List all operator projects.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "switch_project",
            "description": "Switch the active project.",
            "parameters":  {
                "type":       "object",
                "properties": {"name": {"type": "string", "description": "Project name to activate"}},
                "required":   ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "save_note",
            "description": "Save a note to the current project.",
            "parameters":  {
                "type":       "object",
                "properties": {"content": {"type": "string"}},
                "required":   ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "read_notes",
            "description": "Read the notes for the current project.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "cleanup_disk",
            "description": "Free disk space: delete user & system temp files, empty Recycle Bin, report free space before and after. Safe, non-destructive.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "list_voices",
            "description": "List all installed TTS voices available on this system. Call this before set_voice.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "set_voice",
            "description": "Change JARVIS speaking voice to a different installed voice. Use list_voices first to see options.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "voice_name": {"type": "string", "description": "Exact voice name as returned by list_voices"},
                    "rate":       {"type": "integer", "description": "Speech rate: -10 slowest to 10 fastest. Default -1."},
                },
                "required": ["voice_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "list_voice_profiles",
            "description": "List all available JARVIS voice profiles (Kokoro neural voices). Use before set_voice_profile.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "set_voice_profile",
            "description": "Switch the active JARVIS voice profile. Use list_voice_profiles first.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "profile_name": {"type": "string", "description": "Profile name (e.g. jarvis_british, clone_trooper, auto)"},
                },
                "required": ["profile_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "switch_persona",
            "description": "Switch JARVIS active persona: jarvis (classic British), india (warm), ct7567 (military), morgan (reflective).",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "persona_name": {"type": "string", "description": "Persona name: jarvis, india, ct7567, morgan"},
                },
                "required": ["persona_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "save_target",
            "description": "Save a recon/scan target to the current project.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "target": {"type": "string", "description": "Target hostname, IP, or URL"},
                    "notes":  {"type": "string", "description": "Optional notes about the target"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "list_targets",
            "description": "List all saved targets in the current project.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "save_finding",
            "description": "Save a security finding to the current project.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "title":    {"type": "string", "description": "Short finding title"},
                    "detail":   {"type": "string", "description": "Full finding detail"},
                    "severity": {"type": "string", "description": "Severity: critical|high|medium|low|info"},
                    "target":   {"type": "string", "description": "Target this finding applies to"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "list_findings",
            "description": "List all saved findings in the current project.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Autonomy stack tools ──────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "recon_loop_start",
            "description": "Start the autonomous recon loop. JARVIS will hunt targets on a schedule.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "recon_loop_stop",
            "description": "Stop the autonomous recon loop.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "recon_loop_pause",
            "description": "Pause the autonomous recon loop temporarily.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "recon_loop_status",
            "description": "Get the current status of the autonomous recon loop.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "kill_switch_trigger",
            "description": "Emergency stop — halts all autonomous operations immediately.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "kill_switch_reset",
            "description": "Reset the emergency stop and resume autonomous operations.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "watchdog_status",
            "description": "Get health status of all monitored services (Ollama, bridge, jarvis_ops).",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "preference_summary",
            "description": "Show operator approval preference statistics for autonomous tools.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "finding_digest",
            "description": "Show a digest of all findings by severity and top priorities.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "draft_report",
            "description": "Generate a HackerOne-format draft report for a finding. NEVER auto-submits — operator reviews first.",
            "parameters":  {
                "type":       "object",
                "properties": {"finding_id": {"type": "integer", "description": "ID from findings_canonical table"}},
                "required":   ["finding_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "verify_finding",
            "description": "Read-only verification of a finding (HEAD request only — no payloads).",
            "parameters":  {
                "type":       "object",
                "properties": {"finding_id": {"type": "integer", "description": "Finding ID to verify"}},
                "required":   ["finding_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "score_finding",
            "description": "Score a finding for bounty potential using the local AI model.",
            "parameters":  {
                "type":       "object",
                "properties": {"finding_id": {"type": "integer", "description": "Finding ID to score"}},
                "required":   ["finding_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "list_unverified_findings",
            "description": "List all findings that have not been verified yet.",
            "parameters":  {
                "type":       "object",
                "properties": {"program_id": {"type": "integer", "description": "Optional program filter"}},
                "required":   [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "list_report_drafts",
            "description": "List all pending HackerOne report drafts in the reports/ directory.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "calculate_cvss",
            "description": "Calculate CVSS 3.1 base score from vulnerability metric values.",
            "parameters":  {
                "type": "object",
                "properties": {
                    "attack_vector":       {"type": "string", "enum": ["NETWORK","ADJACENT","LOCAL","PHYSICAL"]},
                    "attack_complexity":   {"type": "string", "enum": ["LOW","HIGH"]},
                    "privileges_required": {"type": "string", "enum": ["NONE","LOW","HIGH"]},
                    "user_interaction":    {"type": "string", "enum": ["NONE","REQUIRED"]},
                    "scope":               {"type": "string", "enum": ["UNCHANGED","CHANGED"]},
                    "confidentiality":     {"type": "string", "enum": ["NONE","LOW","HIGH"]},
                    "integrity":           {"type": "string", "enum": ["NONE","LOW","HIGH"]},
                    "availability":        {"type": "string", "enum": ["NONE","LOW","HIGH"]},
                },
                "required": []
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "token_stats",
            "description": "Show monthly local vs cloud LLM usage and estimated cost.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "morning_briefing",
            "description": (
                "Give the operator a morning briefing: current time, San Diego weather, "
                "overnight intelligence summary (new findings, subdomains), and a tactical "
                "suggestion for the day. Call this when the operator asks for their briefing, "
                "morning update, daily summary, or 'what did I miss'."
            ),
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "research_digest",
            "description": "Get a digest of recent CVE intelligence and vulnerability research relevant to active targets.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "search_research",
            "description": "Search stored research items by keyword or severity.",
            "parameters":  {
                "type": "object",
                "properties": {
                    "query":    {"type": "string",  "description": "Keyword to search in title/description"},
                    "severity": {"type": "string",  "description": "Filter by severity: critical, high, medium, low"},
                    "limit":    {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "research_status",
            "description": "Get the current status of the research intelligence engine: which sources are active and when they were last polled.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "research_cves",
            "description": "Show recent CVEs that match active program scope or targets.",
            "parameters":  {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "research_models",
            "description": "Show new LLM model recommendations — models available in Ollama that fit the hardware and are worth pulling.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "db_maintenance",
            "description": "Run database maintenance: get stats, vacuum, or prune old messages.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "action": {
                        "type":        "string",
                        "description": "One of: stats, vacuum, prune_90d, prune_30d",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "strategy_briefing",
            "description": "Get a strategic mission briefing: current target, recon stage, and recommended next action.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Network intelligence tools ────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "get_weather",
            "description": "Get current weather for any city. Defaults to San Diego if no location given.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "location": {"type": "string", "description": "City name (e.g. 'San Diego', 'New York'). Defaults to San Diego."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "dns_lookup",
            "description": "Resolve A and AAAA DNS records for a domain.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain name to resolve (e.g. 'example.com')"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "whois_lookup",
            "description": "Retrieve WHOIS registration information for a domain.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "domain": {"type": "string", "description": "Domain to look up (e.g. 'example.com')"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "geolocate_ip",
            "description": "Geolocate a public IP address: country, region, city, ISP. Does not work on private/loopback IPs.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "ip": {"type": "string", "description": "Public IPv4 address to geolocate"},
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "get_clipboard",
            "description": "Read the current clipboard contents.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "url_analyze",
            "description": "Parse and security-audit a URL: protocol, host, port, path, query params, credentials, flags.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to analyze"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "run_subfinder",
            "description": "Run passive subdomain enumeration against a domain using subfinder. Requires subfinder installed.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "domain": {"type": "string", "description": "Target domain (e.g. 'example.com')"},
                },
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "run_httpx",
            "description": "Probe domains/IPs for live HTTP/HTTPS services with status codes and titles. Requires httpx installed.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "targets": {"type": "string", "description": "Newline-separated list of domains or IPs, or a single host"},
                },
                "required": ["targets"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "run_nuclei",
            "description": "Scan targets for vulnerabilities using nuclei templates. Unsafe tags (dos, bruteforce, rce-active) are automatically stripped. Requires nuclei installed.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "targets":       {"type": "string", "description": "Newline-separated list of URLs/hosts to scan"},
                    "template_tags": {"type": "string", "description": "Comma-separated nuclei template tags. Default: cves,exposed-panels,misconfigs"},
                },
                "required": ["targets"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "list_capabilities",
            "description": "List all JARVIS tool capabilities, grouped by category, with install status for external recon tools.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Program management tools ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "list_programs",
            "description": "List all bug bounty programs with their scope and status.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "create_program",
            "description": "Create a new bug bounty program with scope domains.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "name":           {"type": "string", "description": "Program name (e.g. 'Shopify')"},
                    "platform":       {"type": "string", "description": "Platform: hackerone, bugcrowd, intigriti"},
                    "scope_domains":  {"type": "string", "description": "Comma-separated in-scope domains"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "add_scope",
            "description": "Add a domain to an existing program's scope.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "program_id": {"type": "integer", "description": "Program ID"},
                    "domain":     {"type": "string",  "description": "Domain to add to scope"},
                },
                "required": ["program_id", "domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "program_status",
            "description": "Get status and finding counts for bug bounty programs.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "program_id": {"type": "integer", "description": "Optional: specific program ID"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "set_program_status",
            "description": "Set the status of a bug bounty program (active, paused, completed).",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "program_id": {"type": "integer", "description": "Program ID"},
                    "status":     {"type": "string",  "description": "New status: active, paused, completed"},
                },
                "required": ["program_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "scope_check",
            "description": "Check whether a domain is in scope for a bug bounty program. Returns IN SCOPE or OUT OF SCOPE with program scope list.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "program_id": {"type": "integer", "description": "Program ID to check against"},
                    "domain":     {"type": "string",  "description": "Domain to check (e.g. 'api.example.com')"},
                },
                "required": ["program_id", "domain"],
            },
        },
    },
    # ── Memory subsystem tools ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "remember",
            "description": (
                "Store a fact, preference, or note in long-term memory. "
                "Use when the operator says 'remember that', 'note that', "
                "'my preference is', or similar explicit storage requests."
            ),
            "parameters":  {
                "type":       "object",
                "properties": {
                    "key":         {"type": "string",  "description": "Semantic label for this memory (e.g. 'user.preferred_language', 'project.tesla.scope')"},
                    "value":       {"type": "string",  "description": "The content to remember"},
                    "layer":       {"type": "string",  "description": "Memory layer: semantic (default), preference, project, episodic, system"},
                    "category":    {"type": "string",  "description": "Category: user_fact, user_preference, project_fact, task_state, runtime, inferred"},
                    "confidence":  {"type": "number",  "description": "Confidence 0.0–1.0 (default 1.0 for explicit operator statements)"},
                    "project_id":  {"type": "integer", "description": "Optional project ID this memory belongs to"},
                    "pinned":      {"type": "boolean", "description": "If true, this memory is never pruned (default false)"},
                    "expires_days":{"type": "integer", "description": "Optional: auto-expire after N days"},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "recall",
            "description": (
                "Search long-term memory for facts, preferences, or notes relevant to a query. "
                "Use before answering questions about the operator's preferences, past decisions, "
                "or project-specific facts."
            ),
            "parameters":  {
                "type":       "object",
                "properties": {
                    "query":      {"type": "string",  "description": "What to search for in memory"},
                    "project_id": {"type": "integer", "description": "Optional: restrict to a specific project"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "forget",
            "description": "Soft-delete a memory record by ID. Pinned memories cannot be forgotten.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "memory_id": {"type": "integer", "description": "The memory ID to forget"},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "pin_memory",
            "description": "Pin a memory record so it is never auto-pruned or forgotten.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "memory_id": {"type": "integer", "description": "The memory ID to pin"},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "inspect_memory",
            "description": "List stored memory records, optionally filtered by layer or project.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "layer":      {"type": "string",  "description": "Optional: filter by layer (working, episodic, semantic, preference, project, system)"},
                    "project_id": {"type": "integer", "description": "Optional: filter by project ID"},
                    "limit":      {"type": "integer", "description": "Max records to show (default 20)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "memory_stats",
            "description": "Show memory subsystem statistics: record counts per layer, pinned count, open conflicts.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "memory_hygiene",
            "description": "Run memory maintenance: prune expired/stale records, enforce size caps, promote episodic memories to semantic.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Operator model tools ──────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "operator_model_summary",
            "description": "Returns a summary of the operator's skill levels, strengths, and session history.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "operator_blindspots",
            "description": "Returns a list of security testing techniques the operator has never tried, with actionable hints.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── LLM chain tools ───────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "analyze_scan_results",
            "description": "Multi-step LLM analysis of raw scan output. Returns summary, anomalies, and scored attack hypotheses.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "raw_output": {"type": "string", "description": "Raw scan output text"},
                    "target":     {"type": "string", "description": "Target domain or IP"},
                    "tech_stack": {"type": "string", "description": "Detected technology stack"},
                },
                "required": ["raw_output"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "reason_vulnerability",
            "description": "Reason about whether a CVE applies to a target tech stack and generate exploitation hypotheses.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "cve_id":      {"type": "string"},
                    "description": {"type": "string"},
                    "tech_stack":  {"type": "string"},
                    "target_url":  {"type": "string"},
                },
                "required": ["description", "tech_stack"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "triage_findings",
            "description": "Score all unverified findings and return the top N worth chasing next.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "program_id": {"type": "integer"},
                    "top_n":      {"type": "integer", "description": "Number of top findings to return (default 3)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "suggest_next_action",
            "description": "Suggest the single best next recon or testing action given operator history and current program.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "program_id": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    # ── Intelligence correlator tools ─────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "intel_correlate_now",
            "description": "Run one CVE correlation pass — cross-reference new CVEs against known target tech stacks.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "intel_status",
            "description": "Show intel correlator status: last run time and pending CVE matches for operator review.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Hunt Director tools ───────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "hunt_director_status",
            "description": "Show hunt director state, pending proposals, and auto-approve configuration.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "hunt_director_enable",
            "description": "Enable the hunt director — it will periodically propose the highest-value next recon action for operator review.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "hunt_director_disable",
            "description": "Disable the hunt director loop.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Strategy learner tools ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "strategy_effectiveness",
            "description": "Show tool effectiveness statistics — which tools find bugs most reliably on which tech stacks.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Chatterbox reference clip management ──────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "list_clips",
            "description": "List Chatterbox reference WAV clips available for zero-shot voice cloning, optionally filtered by persona.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "persona": {"type": "string", "description": "Optional persona name to filter clips (e.g. jarvis, india, ct7567, morgan)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "add_clip",
            "description": "Add a new Chatterbox reference WAV clip for a persona. Source file must be 5–30 seconds and >10 KB.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "src_path":    {"type": "string", "description": "Absolute path to the source WAV file"},
                    "persona":     {"type": "string", "description": "Persona name this clip belongs to (e.g. jarvis, india)"},
                    "description": {"type": "string", "description": "Short label for the clip (e.g. primary, soft, battle)"},
                },
                "required": ["src_path", "persona", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "remove_clip",
            "description": "Remove a Chatterbox reference WAV clip by filename.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "name": {"type": "string", "description": "Filename of the clip to remove (e.g. jarvis_primary.wav)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "validate_clip",
            "description": "Validate a WAV file for use as a Chatterbox reference clip: checks duration, sample rate, channels, and file size.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the WAV file to validate"},
                },
                "required": ["path"],
            },
        },
    },
    # ── Camera vision tools ───────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "vision_status",
            "description": "Get camera/vision system status: on/off, people present, known faces count.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "vision_list_known_people",
            "description": "List all people JARVIS knows by face.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "vision_rename_person",
            "description": "Rename a detected person. Use when operator says 'that's my dad, call him Dad'.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "old_name": {"type": "string", "description": "Current name (e.g. Person_1234567890)"},
                    "new_name": {"type": "string", "description": "New name to assign"},
                },
                "required": ["old_name", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "vision_delete_all_faces",
            "description": "Wipe all stored face data completely. Irreversible.",
            "parameters":  {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Browser + presentation tools ─────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name":        "web_search",
            "description": "Search the internet and return the top results.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "query":       {"type": "string",  "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Number of results (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "browse_url",
            "description": "Browse a URL and read its content.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "url":     {"type": "string", "description": "URL to browse"},
                    "extract": {"type": "string", "description": "What to extract: text, title, html (default: text)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name":        "present_topic",
            "description": "Generate an interactive presentation on any topic and deploy it on the second monitor.",
            "parameters":  {
                "type":       "object",
                "properties": {
                    "topic":       {"type": "string",  "description": "Topic to present"},
                    "slide_count": {"type": "integer", "description": "Number of slides (default 8)"},
                },
                "required": ["topic"],
            },
        },
    },
]


_dispatch_log = _logging.getLogger(__name__)


def _validate_target_list(raw: str) -> list[str]:
    """
    Validate a newline-separated list of hosts/URLs for httpx/nuclei.
    Accepts domains, IPs, and HTTP(S) URLs. Logs and drops invalid entries.
    Returns only validated targets.
    """
    valid = []
    for line in raw.splitlines():
        t = line.strip()
        if not t:
            continue
        if t.startswith("http://") or t.startswith("https://"):
            try:
                validate_url(t)
                valid.append(t)
            except ValueError as e:
                _dispatch_log.warning("[dispatch] dropping invalid URL target %r: %s", t, e)
        else:
            try:
                validate_domain(t)
                valid.append(t)
            except ValueError as e:
                _dispatch_log.warning("[dispatch] dropping invalid domain target %r: %s", t, e)
    return valid


# ── Browser + presentation tool implementations ───────────────────────────────

def _tool_web_search(query: str = "", max_results: int = 5, **_) -> str:
    from tools.browser_tools import tool_web_search
    result = tool_web_search(query, max_results)
    return result.get("output", result.get("error", str(result)))


def _tool_browse_url(url: str = "", extract: str = "text", **_) -> str:
    from tools.browser_tools import tool_browse_url
    result = tool_browse_url(url, extract)
    return result.get("output", result.get("error", str(result)))


def _tool_present_topic(topic: str = "", slide_count: int = 8, **_) -> str:
    if not topic:
        return "topic is required"
    try:
        from llm.router import ModelRouter
        router = ModelRouter()
        prompt = (
            f"Create a {slide_count}-slide presentation about: {topic}\n"
            f"Return ONLY valid JSON (no markdown, no code fences) in this format:\n"
            f'{{"title": "...", "slides": [{{"title": "Slide Title", "content": "Detailed content here..."}}]}}\n'
            f"Make content informative, 2-4 paragraphs per slide."
        )
        raw = router.complete([{"role": "user", "content": prompt}], intent="chat")
        import json as _json
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = _json.loads(clean.strip())
        def _launch():
            from gui.windows.presentation_window import launch_presentation
            launch_presentation(data.get('title', topic), data.get('slides', []))
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, _launch)
        except Exception:
            pass
        return f"Presentation '{data.get('title', topic)}' deploying on monitor 2 ({len(data.get('slides', []))} slides)"
    except Exception as e:
        return f"Presentation failed: {e}"


def _dispatch_inner(name: str, args: dict) -> tuple[str, bool]:
    """
    Route a tool call by name to its implementation.
    Returns (output_string, needs_confirmation).
    If needs_confirmation is True, output contains the command to confirm.
    """
    def _extract(result) -> str:
        """Extract string output from ToolResult dict or plain string."""
        if isinstance(result, dict):
            return result.get("output", str(result))
        return str(result)

    if name == "system_status":
        return tool_system_status(), False

    elif name == "self_reflect":
        return tool_self_reflect(args.get("aspect", "capabilities")), False

    elif name == "run_command":
        out = tool_run_command(args.get("command", ""), args.get("confirmed", False))
        if out.startswith("CONFIRM:"):
            return out[8:].strip(), True
        return out, False

    elif name == "open_app":
        return tool_open_app(args.get("app", "")), False

    elif name == "list_projects":
        return tool_list_projects(), False

    elif name == "switch_project":
        return tool_switch_project(args.get("name", "")), False

    elif name == "save_note":
        return tool_save_note(args.get("content", "")), False

    elif name == "read_notes":
        return tool_read_notes(), False

    elif name == "cleanup_disk":
        return tool_cleanup_disk(), False

    elif name == "list_voices":
        return _extract(tool_list_voices()), False

    elif name == "set_voice":
        return _extract(tool_set_voice(
            args.get("voice_name", ""),
            args.get("rate", -1),
        )), False

    elif name == "list_voice_profiles":
        return _extract(tool_list_voice_profiles()), False

    elif name == "set_voice_profile":
        return _extract(tool_set_voice_profile(args.get("profile_name", ""))), False

    elif name == "switch_persona":
        return _extract(tool_switch_persona(args.get("persona_name", ""))), False

    elif name == "save_target":
        return tool_save_target(args.get("target", ""), args.get("notes", "")), False

    elif name == "list_targets":
        return tool_list_targets(), False

    elif name == "save_finding":
        return tool_save_finding(
            args.get("title", ""),
            args.get("detail", ""),
            args.get("severity", "info"),
            args.get("target", ""),
        ), False

    elif name == "list_findings":
        return tool_list_findings(), False

    # ── Autonomy stack ────────────────────────────────────────────────────────
    elif name == "recon_loop_start":
        try:
            from runtime.boot_manager import recon_loop
            if recon_loop:
                recon_loop.start()
                return "Autonomous recon loop started.", False
            return "Recon loop not initialized. Enable RECON_LOOP_ENABLED in config.", False
        except Exception as e:
            return f"Error starting recon loop: {e}", False

    elif name == "recon_loop_stop":
        try:
            from runtime.boot_manager import recon_loop
            if recon_loop:
                recon_loop.stop()
                return "Autonomous recon loop stopped.", False
            return "Recon loop not running.", False
        except Exception as e:
            return f"Error stopping recon loop: {e}", False

    elif name == "recon_loop_pause":
        try:
            from runtime.boot_manager import recon_loop
            if recon_loop:
                recon_loop.pause()
                return "Autonomous recon loop paused.", False
            return "Recon loop not running.", False
        except Exception as e:
            return f"Error pausing recon loop: {e}", False

    elif name == "recon_loop_status":
        try:
            from runtime.boot_manager import recon_loop
            if recon_loop:
                s = recon_loop.status()
                return (
                    f"Recon loop: {'RUNNING' if s['running'] else 'STOPPED'}"
                    f"{'  [PAUSED]' if s['paused'] else ''}\n"
                    f"Cycles: {s['cycles']} | Active jobs: {s['active_jobs']}\n"
                    f"Last cycle: {s['last_cycle'] or 'Never'}\n"
                    f"Quiet hours: {'ACTIVE' if s['quiet_hours_active'] else 'inactive'} | "
                    f"Kill switch: {'ARMED' if s['kill_switch_active'] else 'clear'}"
                ), False
            return "Recon loop not initialized.", False
        except Exception as e:
            return f"Error getting status: {e}", False

    elif name == "kill_switch_trigger":
        try:
            from runtime.kill_switch import get_kill_switch
            get_kill_switch().trigger("operator_voice_command")
            return "EMERGENCY STOP activated. All autonomous operations halted.", False
        except Exception as e:
            return f"Error triggering kill switch: {e}", False

    elif name == "kill_switch_reset":
        try:
            from runtime.kill_switch import get_kill_switch
            get_kill_switch().reset()
            return "Emergency stop cleared. Autonomous operations can resume.", False
        except Exception as e:
            return f"Error resetting kill switch: {e}", False

    elif name == "watchdog_status":
        try:
            from runtime.boot_manager import watchdog
            if watchdog:
                s = watchdog.status()
                lines = ["Service health:"]
                for svc, info in s.items():
                    lines.append(f"  {svc}: {'UP' if info['healthy'] else 'DOWN'} "
                                 f"(restarts: {info['restarts']}/{info['max']})")
                return "\n".join(lines), False
            return "Watchdog not initialized.", False
        except Exception as e:
            return f"Error getting watchdog status: {e}", False

    elif name == "preference_summary":
        try:
            from autonomy.preference_engine import PreferenceEngine
            summary = PreferenceEngine().get_preferences_summary()
            if not summary["tools"]:
                return "No preference data yet.", False
            lines = [f"Approval patterns ({len(summary['tools'])} tools):"]
            for t in summary["tools"][:10]:
                lines.append(f"  {t['tool']}: {t['approval_rate']*100:.0f}% approved "
                             f"({t['total']} decisions)")
            if summary["suggestion_count"]:
                lines.append(f"\n{summary['suggestion_count']} policy update suggestion(s) available.")
            return "\n".join(lines), False
        except Exception as e:
            return f"Error getting preferences: {e}", False

    elif name == "finding_digest":
        return tool_finding_digest(), False

    elif name == "draft_report":
        try:
            from reporting.report_engine import tool_draft_report as _re_draft
            result = _re_draft(int(args.get("finding_id", 0)))
            return result.get("output", str(result)), False
        except Exception as exc:
            return tool_draft_report(int(args.get("finding_id", 0))), False

    elif name == "list_report_drafts":
        try:
            from reporting.report_engine import tool_list_report_drafts as _re_list
            result = _re_list()
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"list_report_drafts unavailable: {exc}", False

    elif name == "calculate_cvss":
        try:
            from reporting.report_engine import tool_calculate_cvss as _re_cvss
            result = _re_cvss(
                attack_vector=args.get("attack_vector", "NETWORK"),
                attack_complexity=args.get("attack_complexity", "LOW"),
                privileges_required=args.get("privileges_required", "NONE"),
                user_interaction=args.get("user_interaction", "NONE"),
                scope=args.get("scope", "UNCHANGED"),
                confidentiality=args.get("confidentiality", "HIGH"),
                integrity=args.get("integrity", "NONE"),
                availability=args.get("availability", "NONE"),
            )
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"calculate_cvss unavailable: {exc}", False

    elif name == "verify_finding":
        return tool_verify_finding(int(args.get("finding_id", 0))), False

    elif name == "score_finding":
        return tool_score_finding(int(args.get("finding_id", 0))), False

    elif name == "list_unverified_findings":
        return tool_list_unverified_findings(args.get("program_id")), False

    elif name == "token_stats":
        try:
            from llm.router import LLMRouter
            s = LLMRouter().get_token_stats()
            return (
                f"LLM routing stats (30 days):\n"
                f"  Local calls: {s['local_calls_month']}\n"
                f"  Cloud calls: {s['cloud_calls_month']}\n"
                f"  Local ratio: {s['local_ratio']*100:.0f}%\n"
                f"  Est. cost:   ${s['estimated_cost_month_usd']:.4f}"
            ), False
        except Exception as e:
            return f"Error getting token stats: {e}", False

    elif name == "morning_briefing":
        try:
            from scheduler.morning_briefing import tool_morning_briefing
            return tool_morning_briefing(), False
        except Exception as exc:
            return f"Briefing unavailable: {exc}", False

    elif name == "research_digest":
        try:
            from research.engine import ResearchEngine
            import config as _rc
            persona = getattr(_rc, 'ACTIVE_PERSONA', 'jarvis')
            items = ResearchEngine().get_unactioned(limit=10)
            if not items:
                return "No unactioned research items. Intelligence queue is clear.", False
            from research.evaluator import get_digest_text
            return get_digest_text(items, persona), False
        except Exception as exc:
            return f"Research digest unavailable: {exc}", False

    elif name == "search_research":
        try:
            from storage.db import get_db
            q     = args.get("query", "").strip()
            sev   = args.get("severity", "").strip().lower()
            limit = int(args.get("limit", 10))
            with get_db() as conn:
                if q and sev:
                    rows = conn.execute(
                        "SELECT id,source,title,severity,url,affects_targets,actioned "
                        "FROM research_items WHERE title LIKE ? AND severity=? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (f"%{q}%", sev, limit)
                    ).fetchall()
                elif q:
                    rows = conn.execute(
                        "SELECT id,source,title,severity,url,affects_targets,actioned "
                        "FROM research_items WHERE title LIKE ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (f"%{q}%", limit)
                    ).fetchall()
                elif sev:
                    rows = conn.execute(
                        "SELECT id,source,title,severity,url,affects_targets,actioned "
                        "FROM research_items WHERE severity=? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (sev, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id,source,title,severity,url,affects_targets,actioned "
                        "FROM research_items ORDER BY created_at DESC LIMIT ?",
                        (limit,)
                    ).fetchall()
            if not rows:
                return "No research items found matching that query.", False
            lines = [f"[{r[3].upper()}] {r[2]} — {r[4] or 'no url'}" for r in rows]
            return "\n".join(lines), False
        except Exception as exc:
            return f"Search failed: {exc}", False

    elif name == "research_status":
        try:
            from storage.db import get_db
            with get_db() as conn:
                total = conn.execute("SELECT COUNT(*) FROM research_items").fetchone()[0]
                unactioned = conn.execute(
                    "SELECT COUNT(*) FROM research_items WHERE actioned=0"
                ).fetchone()[0]
                critical = conn.execute(
                    "SELECT COUNT(*) FROM research_items WHERE severity='critical' AND actioned=0"
                ).fetchone()[0]
            return (
                f"Research engine: {total} total items, {unactioned} unactioned"
                + (f", {critical} critical" if critical else "")
                + ". Sources: NVD CVEs, GitHub advisories, Shodan (if key set), Ollama registry, HackerOne.",
                False
            )
        except Exception as exc:
            return f"Research status unavailable: {exc}", False

    elif name == "research_cves":
        try:
            from storage.db import get_db
            limit = int(args.get("limit", 10))
            with get_db() as conn:
                rows = conn.execute(
                    "SELECT title, severity, url, affects_targets FROM research_items "
                    "WHERE item_type='cve' AND actioned=0 "
                    "ORDER BY CASE severity WHEN 'critical' THEN 4 WHEN 'high' THEN 3 "
                    "WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC, "
                    "created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            if not rows:
                return "No unactioned CVEs in queue. Intelligence is clear.", False
            lines = []
            for r in rows:
                flag = " [AFFECTS TARGETS]" if r[3] else ""
                lines.append(f"[{r[1].upper()}] {r[0]}{flag}")
            return "\n".join(lines), False
        except Exception as exc:
            return f"CVE query failed: {exc}", False

    elif name == "research_models":
        try:
            from research.sources.ollama_registry import OllamaRegistrySource
            from research.evaluator import LLMEvaluator
            source = OllamaRegistrySource()
            items  = source.fetch()
            if not items:
                return "No new model recommendations. All notable models are either installed or exceed available VRAM.", False
            evaluator = LLMEvaluator()
            lines = []
            for item in items:
                ev = evaluator.evaluate(item)
                marker = "✓" if ev["fits_hardware"] else "✗"
                lines.append(f"[{marker}] {item['title']} — {ev['recommendation']}")
            return "\n".join(lines), False
        except Exception as exc:
            return f"Model recommendations unavailable: {exc}", False

    elif name == "db_maintenance":
        action = args.get("action", "stats").lower()
        try:
            from storage.db import db_stats, db_vacuum, db_prune_old_messages
            if action == "vacuum":
                return db_vacuum(), False
            elif action in ("prune_90d", "prune"):
                n = db_prune_old_messages(90)
                return f"Pruned {n} messages older than 90 days.", False
            elif action == "prune_30d":
                n = db_prune_old_messages(30)
                return f"Pruned {n} messages older than 30 days.", False
            else:  # stats
                stats = db_stats()
                lines = [f"  {k}: {v}" for k, v in stats.items()]
                return "Database stats:\n" + "\n".join(lines), False
        except Exception as exc:
            return f"DB maintenance error: {exc}", False

    elif name == "strategy_briefing":
        try:
            from autonomy.strategy import tool_strategy_briefing
            return tool_strategy_briefing(), False
        except Exception as exc:
            return f"Strategy unavailable: {exc}", False

    # ── Network intelligence tools ────────────────────────────────────────────
    elif name == "get_weather":
        return tool_get_weather(args.get("location", "San Diego")), False

    elif name == "dns_lookup":
        _domain = args.get("domain", "")
        try:
            _domain = validate_domain(_domain)
        except ValueError as _e:
            return f"Invalid domain: {_e}", False
        return tool_dns_lookup(_domain), False

    elif name == "whois_lookup":
        _domain = args.get("domain", "")
        try:
            _domain = validate_domain(_domain)
        except ValueError as _e:
            return f"Invalid domain: {_e}", False
        return tool_whois_lookup(_domain), False

    elif name == "geolocate_ip":
        return tool_geolocate_ip(args.get("ip", "")), False

    elif name == "get_clipboard":
        return tool_get_clipboard(), False

    elif name == "url_analyze":
        return tool_url_analyze(args.get("url", "")), False

    elif name == "run_subfinder":
        _domain = args.get("domain", "")
        try:
            _domain = validate_domain(_domain)
        except ValueError as _e:
            return f"Invalid domain: {_e}", False
        return tool_run_subfinder(_domain), False

    elif name == "run_httpx":
        _raw_targets = args.get("targets", "")
        _valid_targets = _validate_target_list(_raw_targets)
        if not _valid_targets:
            return "No valid targets after domain/URL validation.", False
        return tool_run_httpx("\n".join(_valid_targets)), False

    elif name == "run_nuclei":
        _raw_targets = args.get("targets", "")
        _valid_targets = _validate_target_list(_raw_targets)
        if not _valid_targets:
            return "No valid targets after domain/URL validation.", False
        return tool_run_nuclei(
            "\n".join(_valid_targets),
            args.get("template_tags", "cves,exposed-panels,misconfigs"),
        ), False

    elif name == "list_capabilities":
        return tool_list_capabilities(), False

    # ── Program management ────────────────────────────────────────────────────
    elif name == "list_programs":
        return tool_list_programs(), False

    elif name == "create_program":
        return tool_create_program(
            args.get("name", ""),
            args.get("platform", "hackerone"),
            args.get("scope_domains", ""),
        ), False

    elif name == "add_scope":
        prog_id = int(args.get("program_id", 0))
        return tool_add_scope(prog_id, args.get("domain", "")), False

    elif name == "program_status":
        prog_id = args.get("program_id")
        return tool_program_status(int(prog_id) if prog_id else None), False

    elif name == "set_program_status":
        return tool_set_program_status(
            int(args.get("program_id", 0)),
            args.get("status", ""),
        ), False

    elif name == "scope_check":
        return tool_scope_check(
            int(args.get("program_id", 0)),
            args.get("domain", ""),
        ), False

    # ── Memory subsystem tools ────────────────────────────────────────────────

    elif name == "remember":
        if not _MEMORY_AVAILABLE:
            return "Memory subsystem not available.", False
        return tool_remember(
            key=args.get("key", ""),
            value=args.get("value", ""),
            layer=args.get("layer", "semantic"),
            category=args.get("category", "user_fact"),
            confidence=float(args.get("confidence", 1.0)),
            project_id=args.get("project_id"),
            pinned=bool(args.get("pinned", False)),
            expires_days=args.get("expires_days"),
        ), False

    elif name == "recall":
        if not _MEMORY_AVAILABLE:
            return "Memory subsystem not available.", False
        return tool_recall(
            query=args.get("query", ""),
            project_id=args.get("project_id"),
        ), False

    elif name == "forget":
        if not _MEMORY_AVAILABLE:
            return "Memory subsystem not available.", False
        return tool_forget(int(args.get("memory_id", 0))), False

    elif name == "pin_memory":
        if not _MEMORY_AVAILABLE:
            return "Memory subsystem not available.", False
        return tool_pin_memory(int(args.get("memory_id", 0))), False

    elif name == "inspect_memory":
        if not _MEMORY_AVAILABLE:
            return "Memory subsystem not available.", False
        return tool_inspect_memory(
            layer=args.get("layer"),
            project_id=args.get("project_id"),
            limit=int(args.get("limit", 20)),
        ), False

    elif name == "memory_stats":
        if not _MEMORY_AVAILABLE:
            return "Memory subsystem not available.", False
        return tool_memory_stats(), False

    elif name == "memory_hygiene":
        if not _MEMORY_AVAILABLE:
            return "Memory subsystem not available.", False
        return tool_memory_hygiene(), False

    # ── Operator model tools ──────────────────────────────────────────────────
    elif name == "operator_model_summary":
        try:
            from memory.operator_model import tool_operator_model_summary
            result = tool_operator_model_summary()
            return result.get("output", "No operator model data."), False
        except Exception as e:
            return f"Operator model unavailable: {e}", False

    elif name == "operator_blindspots":
        try:
            from memory.operator_model import tool_operator_blindspots
            result = tool_operator_blindspots()
            return result.get("output", "No blindspot data."), False
        except Exception as e:
            return f"Operator blindspots unavailable: {e}", False

    # ── LLM chain tools ───────────────────────────────────────────────────────
    elif name == "analyze_scan_results":
        try:
            from llm.chains.recon_analyst import tool_analyze_scan_results
            result = tool_analyze_scan_results(
                raw_output=args.get("raw_output", ""),
                target=args.get("target", ""),
                tech_stack=args.get("tech_stack", ""),
            )
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"Scan analysis unavailable: {exc}", False

    elif name == "reason_vulnerability":
        try:
            from llm.chains.vuln_reasoner import tool_reason_vulnerability
            result = tool_reason_vulnerability(
                cve_id=args.get("cve_id", ""),
                description=args.get("description", ""),
                tech_stack=args.get("tech_stack", ""),
                target_url=args.get("target_url", ""),
            )
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"Vulnerability reasoning unavailable: {exc}", False

    elif name == "triage_findings":
        try:
            from llm.chains.triage_engine import tool_triage_findings
            result = tool_triage_findings(
                program_id=args.get("program_id", 0),
                top_n=args.get("top_n", 3),
            )
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"Triage unavailable: {exc}", False

    elif name == "suggest_next_action":
        try:
            from llm.chains.strategy_advisor import tool_suggest_next_action
            result = tool_suggest_next_action(program_id=args.get("program_id", 0))
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"Strategy advisor unavailable: {exc}", False

    # ── Intelligence correlator tools ─────────────────────────────────────────
    elif name == "intel_correlate_now":
        try:
            from intelligence.correlator import tool_intel_correlate_now
            result = tool_intel_correlate_now()
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"Intel correlator unavailable: {exc}", False

    elif name == "intel_status":
        try:
            from intelligence.correlator import tool_intel_status
            result = tool_intel_status()
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"Intel status unavailable: {exc}", False

    elif name == "strategy_effectiveness":
        try:
            from autonomy.strategy_learner import tool_strategy_effectiveness
            result = tool_strategy_effectiveness()
            return result.get("output", str(result)), False
        except Exception as exc:
            return f"Strategy effectiveness unavailable: {exc}", False

    # ── Chatterbox reference clip management ──────────────────────────────────
    elif name == "list_clips":
        result = tool_list_clips(persona=args.get("persona"))
        return result.get("output", str(result)), False

    elif name == "add_clip":
        result = tool_add_clip(
            src_path=args.get("src_path", ""),
            persona=args.get("persona", ""),
            description=args.get("description", ""),
        )
        return result.get("output", str(result)), False

    elif name == "remove_clip":
        result = tool_remove_clip(name=args.get("name", ""))
        return result.get("output", str(result)), False

    elif name == "validate_clip":
        result = tool_validate_clip(path=args.get("path", ""))
        return result.get("output", str(result)), False

    # ── Camera vision tools ────────────────────────────────────────────────────
    elif name == "vision_status":
        result = _vision_status()
        enabled = result.get("enabled", False)
        present = result.get("present", [])
        known   = result.get("known", 0)
        present_str = ", ".join(present) if present else "nobody"
        return (
            f"Vision: {'ENABLED' if enabled else 'DISABLED'} | "
            f"Present: {present_str} | Known faces: {known}"
        ), False

    elif name == "vision_list_known_people":
        result = _vision_list_known_people()
        if "error" in result:
            return f"Vision list error: {result['error']}", False
        people = result.get("people", [])
        if not people:
            return "No known faces stored yet.", False
        lines = [f"Known faces ({len(people)}):"]
        for p in people:
            notes = f" — {p['notes']}" if p.get("notes") else ""
            lines.append(f"  {p['name']}  (first seen: {p['first_seen']}, visits: {p['visits']}){notes}")
        return "\n".join(lines), False

    elif name == "vision_rename_person":
        result = _vision_rename_person(
            args.get("old_name", ""), args.get("new_name", "")
        )
        if result.get("success"):
            return f"Renamed: {result['renamed']}", False
        return f"Rename failed: {result.get('error', 'person not found')}", False

    elif name == "vision_delete_all_faces":
        result = _vision_delete_all_faces()
        if result.get("success"):
            return result.get("message", "All face data deleted."), False
        return f"Delete failed: {result.get('error', 'unknown error')}", False

    # ── Browser + presentation tools ─────────────────────────────────────────
    elif name == "web_search":
        return _tool_web_search(**args), False

    elif name == "browse_url":
        return _tool_browse_url(**args), False

    elif name == "present_topic":
        return _tool_present_topic(**args), False

    else:
        return f"Unknown tool: {name}", False


def dispatch(name: str, args: dict) -> tuple[str, bool]:
    """Public dispatch entry-point with response cache layer."""
    # Response cache — check before dispatching
    try:
        from llm.response_cache import response_cache, NEVER_CACHE as _NC
        import config as _cfg
        if getattr(_cfg, 'RESPONSE_CACHE_ENABLED', True) and name not in _NC:
            _cached = response_cache.get(name, args)
            if _cached is not None:
                return _cached
    except Exception:
        pass

    result = _dispatch_inner(name, args)

    # Store in cache if result is ok
    try:
        from llm.response_cache import response_cache
        _output, _needs_confirm = result
        if not _needs_confirm and not _output.startswith("Unknown tool:"):
            response_cache.set(name, args, result)
            # Invalidate stale entries for mutation tools
            response_cache.invalidate_for(name)
    except Exception:
        pass

    return result


# ── Parallel tool execution ───────────────────────────────────────────────────
import concurrent.futures as _cf
from concurrent.futures import ThreadPoolExecutor as _TPE

# Tools safe to run in parallel — all I/O-bound, no shared mutable state
_PARALLEL_SAFE: frozenset = frozenset({
    "dns_lookup", "whois_lookup", "geolocate_ip", "url_analyze",
    "scope_check", "list_programs", "list_findings", "list_targets",
    "list_projects", "system_status", "operator_model_summary",
    "research_digest", "search_research", "watchdog_status",
    "safety_status", "memory_stats", "list_capabilities",
})

_TOOL_EXECUTOR: _TPE = _TPE(max_workers=6, thread_name_prefix="jarvis_tool")


def dispatch_parallel(tool_calls: list) -> list:
    """
    Execute multiple tool calls. Parallel-safe tools run concurrently.
    Non-safe tools run sequentially. Returns results in original order.

    SAFETY: Only _PARALLEL_SAFE tools run in parallel threads.
            All other tools (network scans, mutations) run sequentially.
    """
    if len(tool_calls) <= 1:
        return [dispatch(tc["name"], tc.get("arguments", {})) for tc in tool_calls]

    parallel_idxs  = [i for i, tc in enumerate(tool_calls) if tc["name"] in _PARALLEL_SAFE]
    sequential_idxs = [i for i, tc in enumerate(tool_calls) if tc["name"] not in _PARALLEL_SAFE]

    results: list = [{}] * len(tool_calls)

    # Run parallel-safe calls concurrently
    if parallel_idxs:
        futures = {
            _TOOL_EXECUTOR.submit(
                dispatch, tool_calls[i]["name"], tool_calls[i].get("arguments", {})
            ): i
            for i in parallel_idxs
        }
        for future in _cf.as_completed(futures, timeout=30):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = ("", False)

    # Run sequential calls one at a time
    for i in sequential_idxs:
        try:
            results[i] = dispatch(tool_calls[i]["name"], tool_calls[i].get("arguments", {}))
        except Exception as e:
            results[i] = (f"Tool error: {e}", False)

    return results


# Populate REGISTRY dict for tool-existence checks
REGISTRY.update({
    # existing tools
    "system_status": tool_system_status,
    "run_command": tool_run_command,
    "open_app": tool_open_app,
    "list_projects": tool_list_projects,
    "switch_project": tool_switch_project,
    "save_note": tool_save_note,
    "read_notes": tool_read_notes,
    "cleanup_disk": tool_cleanup_disk,
    "list_voices": tool_list_voices,
    "set_voice": tool_set_voice,
    "list_voice_profiles": tool_list_voice_profiles,
    "set_voice_profile": tool_set_voice_profile,
    "switch_persona": tool_switch_persona,
    "save_target": tool_save_target,
    "list_targets": tool_list_targets,
    "save_finding": tool_save_finding,
    "list_findings": tool_list_findings,
    # autonomy tools
    "recon_loop_start": None,
    "recon_loop_stop": None,
    "recon_loop_pause": None,
    "recon_loop_status": None,
    "kill_switch_trigger": None,
    "kill_switch_reset": None,
    "watchdog_status": None,
    "preference_summary": None,
    "finding_digest": tool_finding_digest,
    "draft_report":       lambda **kw: __import__('reporting.report_engine', fromlist=['tool_draft_report']).tool_draft_report(**kw),
    "list_report_drafts": lambda **_:  __import__('reporting.report_engine', fromlist=['tool_list_report_drafts']).tool_list_report_drafts(),
    "calculate_cvss":     lambda **kw: __import__('reporting.report_engine', fromlist=['tool_calculate_cvss']).tool_calculate_cvss(**kw),
    "verify_finding": tool_verify_finding,
    "score_finding": tool_score_finding,
    "list_unverified_findings": tool_list_unverified_findings,
    "token_stats": None,
    "research_digest": None,
    "search_research": None,
    "research_status": None,
    "research_cves":   None,
    "research_models": None,
    "db_maintenance": None,
    "strategy_briefing": None,
    # network intelligence
    "get_weather":       tool_get_weather,
    "dns_lookup":        tool_dns_lookup,
    "whois_lookup":      tool_whois_lookup,
    "geolocate_ip":      tool_geolocate_ip,
    "get_clipboard":     tool_get_clipboard,
    "url_analyze":       tool_url_analyze,
    "run_subfinder":     tool_run_subfinder,
    "run_httpx":         tool_run_httpx,
    "run_nuclei":        tool_run_nuclei,
    "list_capabilities": tool_list_capabilities,
    # program management
    "list_programs":      tool_list_programs,
    "create_program":     tool_create_program,
    "add_scope":          tool_add_scope,
    "program_status":     tool_program_status,
    "set_program_status": tool_set_program_status,
    "scope_check":        tool_scope_check,
    # memory subsystem
    "remember":           tool_remember        if _MEMORY_AVAILABLE else None,
    "recall":             tool_recall          if _MEMORY_AVAILABLE else None,
    "forget":             tool_forget          if _MEMORY_AVAILABLE else None,
    "pin_memory":         tool_pin_memory      if _MEMORY_AVAILABLE else None,
    "inspect_memory":     tool_inspect_memory  if _MEMORY_AVAILABLE else None,
    "memory_stats":       tool_memory_stats    if _MEMORY_AVAILABLE else None,
    "memory_hygiene":     tool_memory_hygiene  if _MEMORY_AVAILABLE else None,
    # operator model
    "operator_model_summary": lambda **_: __import__('memory.operator_model', fromlist=['tool_operator_model_summary']).tool_operator_model_summary(),
    "operator_blindspots":    lambda **_: __import__('memory.operator_model', fromlist=['tool_operator_blindspots']).tool_operator_blindspots(),
    # LLM chain tools
    "analyze_scan_results": lambda **kw: __import__('llm.chains.recon_analyst',   fromlist=['tool_analyze_scan_results']).tool_analyze_scan_results(**kw),
    "reason_vulnerability": lambda **kw: __import__('llm.chains.vuln_reasoner',   fromlist=['tool_reason_vulnerability']).tool_reason_vulnerability(**kw),
    "triage_findings":      lambda **kw: __import__('llm.chains.triage_engine',   fromlist=['tool_triage_findings']).tool_triage_findings(**kw),
    "suggest_next_action":  lambda **kw: __import__('llm.chains.strategy_advisor',fromlist=['tool_suggest_next_action']).tool_suggest_next_action(**kw),
    # intelligence correlator
    "intel_correlate_now": lambda **_: __import__('intelligence.correlator', fromlist=['tool_intel_correlate_now']).tool_intel_correlate_now(),
    "intel_status":        lambda **_: __import__('intelligence.correlator', fromlist=['tool_intel_status']).tool_intel_status(),
    # hunt director
    "hunt_director_status":  lambda **_: __import__('autonomy.hunt_director', fromlist=['tool_hunt_director_status']).tool_hunt_director_status(),
    "hunt_director_enable":  lambda **_: __import__('autonomy.hunt_director', fromlist=['tool_hunt_director_enable']).tool_hunt_director_enable(),
    "hunt_director_disable": lambda **_: __import__('autonomy.hunt_director', fromlist=['tool_hunt_director_disable']).tool_hunt_director_disable(),
    # strategy learner
    "strategy_effectiveness": lambda **_: __import__('autonomy.strategy_learner', fromlist=['tool_strategy_effectiveness']).tool_strategy_effectiveness(),
    # chatterbox reference clip management
    "list_clips":    tool_list_clips,
    "add_clip":      tool_add_clip,
    "remove_clip":   tool_remove_clip,
    "validate_clip": tool_validate_clip,
    # camera vision tools
    "vision_status":            lambda **k: _vision_status(),
    "vision_list_known_people": lambda **k: _vision_list_known_people(),
    "vision_rename_person":     lambda **k: _vision_rename_person(k.get("old_name", ""), k.get("new_name", "")),
    "vision_delete_all_faces":  lambda **k: _vision_delete_all_faces(),
    # browser + presentation
    "web_search":    lambda **k: _tool_web_search(**k),
    "browse_url":    lambda **k: _tool_browse_url(**k),
    "present_topic": lambda **k: _tool_present_topic(**k),
})
