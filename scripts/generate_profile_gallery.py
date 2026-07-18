import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

# Define paths relative to the script's location
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
PROFILES_DIR = PROJECT_ROOT / "pytestlab" / "profiles"
GALLERY_MD_PATH = PROJECT_ROOT / "docs" / "en" / "profiles" / "gallery.md"
REPOSITORY_BLOB_URL = "https://github.com/labiium/pytestlab/blob/master"


def _last_updated(profile_file: Path) -> str:
    """Return the last committed date without making generated output machine-specific."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cs", "--", str(profile_file)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "Not yet committed"


def _profile_data(profile_file: Path) -> dict:
    with profile_file.open(encoding="utf-8") as f:
        profile_data = yaml.safe_load(f)
    if not isinstance(profile_data, dict):
        raise ValueError("profile root must be a mapping")
    if any(not isinstance(key, str) for key in profile_data):
        raise ValueError("profile root keys must be strings")
    if len(profile_data) == 1 and isinstance(next(iter(profile_data.values())), dict):
        data_to_extract_from = next(iter(profile_data.values()))
    else:
        data_to_extract_from = profile_data
    if not isinstance(data_to_extract_from, dict):
        raise ValueError("profile data block must be a mapping")
    return data_to_extract_from


def _write_text_atomic(dest_path: Path, content: str) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(f".{dest_path.name}.tmp")
    tmp_path.write_text(content)
    os.replace(tmp_path, dest_path)


def generate_profile_gallery(
    profiles_dir: Path = PROFILES_DIR,
    dest_path: Path = GALLERY_MD_PATH,
) -> int:
    """
    Scans for instrument profile YAML files, extracts key information,
    and generates a Markdown gallery page.
    """
    markdown_snippets = []
    failures: list[tuple[Path, str]] = []
    profile_files = sorted(profiles_dir.rglob("*.yaml"))

    if not profile_files:
        print("No profile YAML files found.")
        # Fallback content if no profiles are found
        content = f"""# Instrument Profile Gallery

This page lists available instrument profiles.

*No instrument profiles found in `{profiles_dir}`.*
"""
        _write_text_atomic(dest_path, content)
        return 0

    for profile_file in profile_files:
        try:
            data_to_extract_from = _profile_data(profile_file)

            manufacturer = data_to_extract_from.get("manufacturer", "N/A")
            model = data_to_extract_from.get(
                "model", profile_file.stem
            )  # Fallback to filename stem
            default_type = "accessory" if "accessories" in profile_file.parts else "Not specified"
            device_type = data_to_extract_from.get("device_type", default_type)
            code_owners = data_to_extract_from.get("code_owners", [])
            last_updated = data_to_extract_from.get("last_updated", _last_updated(profile_file))

            try:
                relative_profile_path = profile_file.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                relative_profile_path = profile_file.as_posix()

            owner_line = ""
            if code_owners:
                owner_links = ", ".join(
                    f"[`@{owner}`](https://github.com/{owner})" for owner in code_owners
                )
                owner_line = f"- **Code Owners:** {owner_links}\n"

            snippet = f"""### {manufacturer} {model}

- **Device Type:** `{device_type}`
- **Profile:** [`{profile_file.name}`]({REPOSITORY_BLOB_URL}/{relative_profile_path})
{owner_line}- **Last Updated:** {last_updated}
"""
            markdown_snippets.append(snippet)

        except yaml.YAMLError as e:
            failures.append((profile_file, f"YAML error: {e}"))
        except Exception as e:
            failures.append((profile_file, f"{type(e).__name__}: {e}"))

    if failures:
        for profile_file, error in failures:
            print(f"Error processing file {profile_file}: {error}", file=sys.stderr)
        print(f"{len(failures)} profile(s) failed; gallery was not updated.", file=sys.stderr)
        return 1

    # Construct the full Markdown page content
    gallery_content = f"""---
title: Profile Gallery
description: Built-in PyTestLab instrument profiles for oscilloscopes, power supplies, meters, loads, and analyzers.
---

# Instrument Profile Gallery

These profiles are available out of the box and live in `pytestlab/profiles/`. Use a profile by its repository-relative key, such as `keysight/DSOX1204G`.
{"---" if markdown_snippets else ""}
"""
    if markdown_snippets:
        gallery_content += "\n\n".join(markdown_snippets)
    else:
        gallery_content += "\n*No instrument profiles could be processed successfully.*"

    # Write the generated content to the gallery Markdown file
    try:
        _write_text_atomic(dest_path, gallery_content)
        print(f"Successfully generated instrument profile gallery at: {dest_path}")
        return 0
    except OSError as e:
        print(f"Error writing to {dest_path}: {e}", file=sys.stderr)
        return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the PyTestLab profile gallery")
    parser.add_argument("--profiles-dir", type=Path, default=PROFILES_DIR)
    parser.add_argument("--dest", type=Path, default=GALLERY_MD_PATH)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(generate_profile_gallery(profiles_dir=args.profiles_dir, dest_path=args.dest))
