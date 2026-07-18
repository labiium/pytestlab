"""Small MkDocs build hooks for the custom PyTestLab documentation theme."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from mkdocs.plugins import event_priority


def _notebook_prose(path: Path) -> tuple[str, str]:
    """Extract searchable prose from Markdown cells without Jupyter's inlined assets."""
    notebook = json.loads(path.read_text(encoding="utf-8"))
    markdown = "\n\n".join(
        "".join(cell.get("source", []))
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "markdown"
    )
    title_match = re.search(r"^#\s+(.+)$", markdown, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem.replace("_", " ").title()
    markdown = re.sub(
        r"<(style|script)\b[^>]*>.*?</\1>", " ", markdown, flags=re.DOTALL | re.IGNORECASE
    )
    markdown = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    markdown = re.sub(r"<[^>]+>", " ", markdown)
    markdown = re.sub(r"!\[[^]]*]\([^)]*\)", " ", markdown)
    markdown = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", markdown)
    markdown = re.sub(r"^[#>*+-]+\s*", "", markdown, flags=re.MULTILINE)
    markdown = re.sub(r"[`_*|]", "", markdown)
    prose = re.sub(r"\s+", " ", html.unescape(markdown)).strip()
    return title, prose


@event_priority(-100)
def on_post_build(config: Any) -> None:
    """Replace notebook-generated search noise with compact Markdown-cell prose."""
    site_dir = Path(config.site_dir)
    index_path = site_dir / "search" / "search_index.json"
    if not index_path.exists():
        return

    index = json.loads(index_path.read_text(encoding="utf-8"))
    documents = [
        document
        for document in index.get("docs", [])
        if not str(document.get("location", "")).startswith("tutorials/")
    ]
    tutorials_dir = Path(config.docs_dir) / "tutorials"
    for notebook_path in sorted(tutorials_dir.glob("*.ipynb")):
        title, prose = _notebook_prose(notebook_path)
        documents.append(
            {
                "title": title,
                "text": prose,
                "location": f"tutorials/{notebook_path.stem}/",
            }
        )

    index["docs"] = documents
    index.pop("index", None)
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
