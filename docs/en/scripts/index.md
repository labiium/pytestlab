---
title: Documentation tooling
description: Contributor utilities used to maintain PyTestLab profiles and documentation quality.
---

# Documentation tooling

PyTestLab keeps its documentation utilities in the repository-level [`scripts/`](https://github.com/labiium/pytestlab/tree/master/scripts) directory. These tools are intended for contributors rather than end users.

## Generate the instrument profile gallery

`generate_profile_gallery.py` rebuilds the published [Instrument Profile Gallery](../profiles/gallery.md) from the YAML files in `pytestlab/profiles/`.

```bash
.venv/bin/python scripts/generate_profile_gallery.py
```

Run it after adding or updating an instrument profile. Commit the regenerated gallery with the profile change.

## Bootstrap profiles from PyMeasure

`bootstrap_from_pymeasure.py` helps contributors create initial PyTestLab profile data from compatible PyMeasure drivers. Review and test generated output before committing it; generated profiles are a starting point, not a substitute for hardware validation.

```bash
.venv/bin/python scripts/bootstrap_from_pymeasure.py --help
```

## Build and validate the docs

Use the strict build locally before opening a pull request:

```bash
JUPYTER_PLATFORM_DIRS=1 .venv/bin/mkdocs build --strict -f docs/mkdocs.yml
.venv/bin/python scripts/check_docs.py
```

For notebook presentation conventions, see the [Notebook Styling Guide](../user_guide/notebook_styling.md).
