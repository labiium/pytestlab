"""Regression checks for generated PyTestLab documentation."""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = PROJECT_ROOT / "site"


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []
    index_path = SITE_DIR / "search" / "search_index.json"
    require(index_path.exists(), "search index is missing", failures)
    if index_path.exists():
        index_text = index_path.read_text(encoding="utf-8")
        require(index_path.stat().st_size < 500_000, "search index exceeds 500 KB", failures)
        require("bp3-input" not in index_text, "search index contains Blueprint CSS", failures)
        require(
            "ClipboardCopyElement" not in index_text,
            "search index contains Jupyter JavaScript",
            failures,
        )
        index = json.loads(index_text)
        tutorials = [
            doc for doc in index.get("docs", []) if doc.get("location", "").startswith("tutorials/")
        ]
        require(
            len(tutorials) == 8,
            "search index does not contain exactly eight compact tutorial entries",
            failures,
        )
        require(
            any("simulation mode" in doc.get("text", "").lower() for doc in tutorials),
            "tutorial prose is not searchable",
            failures,
        )

    getting_started = SITE_DIR / "user_guide" / "getting_started" / "index.html"
    require(getting_started.exists(), "Getting Started HTML is missing", failures)
    if getting_started.exists():
        html = getting_started.read_text(encoding="utf-8")
        require(
            "notebook-enhancements" not in html, "ordinary guide loads notebook assets", failures
        )
        require("polyfill.io" not in html, "ordinary guide loads polyfill.io", failures)
        require("fonts.googleapis.com" not in html, "ordinary guide loads Google Fonts", failures)
        require('class="skip-link"' in html, "skip link is missing", failures)
        require('rel="canonical"' in html, "canonical URL is missing", failures)
        require('property="og:title"' in html, "Open Graph metadata is missing", failures)
        require('class="headerlink"' in html, "heading permalinks are missing", failures)

    error_page = SITE_DIR / "404.html"
    require(error_page.exists(), "root 404.html is missing", failures)
    if error_page.exists():
        error_html = error_page.read_text(encoding="utf-8")
        require(
            'class="docs-sidebar"' not in error_html,
            "404 page renders the documentation sidebar",
            failures,
        )

    oversized_api_pages = []
    for path in (SITE_DIR / "api").rglob("index.html"):
        if path.stat().st_size > 150_000:
            oversized_api_pages.append(
                f"{path.relative_to(SITE_DIR)} ({path.stat().st_size} bytes)"
            )
    require(
        not oversized_api_pages,
        f"API pages exceed 150 KB: {', '.join(oversized_api_pages)}",
        failures,
    )

    built_html = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in SITE_DIR.rglob("*.html")
    )
    require("polyfill.io" not in built_html, "built site contains polyfill.io", failures)
    require("fonts.googleapis.com" not in built_html, "built site contains Google Fonts", failures)

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        return 1
    print("Documentation regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
