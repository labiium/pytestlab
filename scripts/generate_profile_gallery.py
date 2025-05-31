import yaml
from pathlib import Path

# Define paths relative to the script's location
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
PROFILES_DIR = PROJECT_ROOT / "pytestlab" / "profiles"
GALLERY_MD_PATH = PROJECT_ROOT / "docs" / "profiles" / "gallery.md"

def generate_profile_gallery():
    """
    Scans for instrument profile YAML files, extracts key information,
    and generates a Markdown gallery page.
    """
    markdown_snippets = []
    profile_files = sorted(PROFILES_DIR.rglob("*.yaml"))

    if not profile_files:
        print("No profile YAML files found.")
        # Fallback content if no profiles are found
        content = f"""# Instrument Profile Gallery

This page lists available instrument profiles.

*No instrument profiles found in `{PROFILES_DIR}`.*
"""
        GALLERY_MD_PATH.write_text(content)
        return

    for profile_file in profile_files:
        try:
            with open(profile_file, 'r') as f:
                profile_data = yaml.safe_load(f)

            # Extract information (handle potential missing keys gracefully)
            # The top-level key is often the model or a unique identifier
            # For profiles like keysight/E36313A.yaml, the data is nested under a key like 'E36313A'
            
            # Try to find the main data block if it's nested
            main_key = None
            if len(profile_data) == 1 and isinstance(list(profile_data.values())[0], dict):
                main_key = list(profile_data.keys())[0]
                data_to_extract_from = profile_data[main_key]
            else:
                # Assume flat structure or try to find common keys at root
                data_to_extract_from = profile_data

            manufacturer = data_to_extract_from.get('manufacturer', 'N/A')
            model = data_to_extract_from.get('model', profile_file.stem) # Fallback to filename stem
            device_type = data_to_extract_from.get('device_type', 'N/A')

            # Create a relative path to the profile from the docs directory
            # gallery.md is in docs/profiles/
            # profile_file is like /path/to/project/pytestlab/profiles/keysight/E36313A.yaml
            # We want ../../pytestlab/profiles/keysight/E36313A.yaml
            relative_profile_path = Path("../../") / profile_file.relative_to(PROJECT_ROOT)
            
            snippet = f"""### {manufacturer} {model}

- **Device Type:** `{device_type}`
- **Profile:** [`{profile_file.name}`]({relative_profile_path})
"""
            markdown_snippets.append(snippet)

        except yaml.YAMLError as e:
            print(f"Error parsing YAML file {profile_file}: {e}")
        except Exception as e:
            print(f"Error processing file {profile_file}: {e}")

    # Construct the full Markdown page content
    gallery_content = f"""# Instrument Profile Gallery

This page lists available instrument profiles.
{"---" if markdown_snippets else ""}
"""
    if markdown_snippets:
        gallery_content += "\n\n".join(markdown_snippets)
    else:
        gallery_content += "\n*No instrument profiles could be processed successfully.*"

    # Write the generated content to the gallery Markdown file
    try:
        GALLERY_MD_PATH.parent.mkdir(parents=True, exist_ok=True) # Ensure docs/profiles exists
        GALLERY_MD_PATH.write_text(gallery_content)
        print(f"Successfully generated instrument profile gallery at: {GALLERY_MD_PATH}")
    except IOError as e:
        print(f"Error writing to {GALLERY_MD_PATH}: {e}")

if __name__ == "__main__":
    generate_profile_gallery()