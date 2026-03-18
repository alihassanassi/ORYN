"""
tools/browser_tools.py – JARVIS browser automation tools.

Full internet access via Playwright (async, headless or visible).
JARVIS can browse, read, search, and interact with the web.

Requires: pip install playwright && playwright install chromium
"""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)


def tool_web_search(query: str, max_results: int = 5) -> dict:
    """Search the web and return clean results."""
    try:
        from playwright.sync_api import sync_playwright
        import urllib.parse
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(
                f"https://www.google.com/search?q={urllib.parse.quote(query)}",
                timeout=15000
            )
            results = page.evaluate("""
                Array.from(document.querySelectorAll('.g')).slice(0, 10).map(el => ({
                    title:   el.querySelector('h3')?.textContent || '',
                    url:     el.querySelector('a')?.href || '',
                    snippet: el.querySelector('.VwiC3b')?.textContent || ''
                })).filter(r => r.title)
            """)
            browser.close()
        lines = []
        for i, r in enumerate(results[:max_results]):
            lines.append(f"{i+1}. {r['title']}")
            lines.append(f"   {r['url']}")
            if r['snippet']:
                lines.append(f"   {r['snippet']}")
        return {"success": True, "output": "\n".join(lines), "count": len(results)}
    except ImportError:
        return {"success": False, "error": "Playwright not installed. Run: pip install playwright && playwright install chromium"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_browse_url(url: str, extract: str = "text") -> dict:
    """Browse a URL and extract its content."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            if extract == "text":
                content = page.evaluate("document.body.innerText")[:4000]
            elif extract == "title":
                content = page.title()
            else:
                content = page.content()[:4000]
            title = page.title()
            browser.close()
        return {"success": True, "output": content, "title": title, "url": url}
    except ImportError:
        return {"success": False, "error": "Playwright not installed."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_youtube_search(query: str) -> dict:
    """Search YouTube and return video titles and URLs."""
    return tool_web_search(f"site:youtube.com {query}")
