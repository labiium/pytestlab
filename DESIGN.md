# Design

## Source of truth

- Status: Active
- Last refreshed: 2026-07-23
- Primary product surfaces: PyTestLab documentation and executable tutorials
- Evidence reviewed: `docs/mkdocs.yml`, `docs/themes/labiium_photon/`, `docs/en/stylesheets/notebook-enhancements.css`, `docs/en/user_guide/notebook_styling.md`, and the supplied tutorial screenshot

## Brand

- Personality: precise, modern, optimistic, and useful to working scientists
- Trust signals: simulation-first examples, explicit cleanup, reproducible data, and clear hardware boundaries
- Avoid: decorative hero copy that overwhelms the lesson, fake claims, and malformed Markdown

## Product goals

- Goals: help readers move from a safe simulated measurement to a real, inspectable experiment; make every example runnable; explain why each API choice matters
- Non-goals: teaching general Python or hiding hardware-specific behavior behind opaque helpers
- Success signals: readers can run the notebook without instruments, inspect a tabular result, plot it, export it, and identify the one line to change for hardware

## Personas and jobs

- Primary personas: engineers and scientists learning PyTestLab; maintainers validating documentation examples
- User jobs: prototype a measurement workflow, understand the session model, and carry a tested pattern into a lab project
- Key contexts of use: local notebooks, MkDocs-rendered tutorials, and CI validation without connected instruments

## Information architecture

- Primary navigation: Docs, Tutorials, API, Instruments, Community
- Core routes/screens: tutorial landing pages and notebook-rendered tutorial pages
- Content hierarchy: outcome and prerequisites -> mental model -> runnable workflow -> inspection and validation -> export -> hardware handoff

## Design principles

- Teach the workflow, not a collection of disconnected API calls.
- Simulation is the default path; real hardware is an explicit, bounded adaptation.
- Keep prose scannable and code cells short enough to copy into a project.
- Prefer visible evidence—tables, assertions, and saved artifacts—over celebratory filler.
- Tradeoff: retain the dark notebook presentation and brand accents while reducing inline styling that competes with the content.

## Visual language

- Color: use the existing violet-to-aqua PyTestLab accents and dark notebook surfaces from the theme and notebook stylesheet
- Typography: inherit the existing documentation typography; use Markdown headings rather than large HTML banners
- Spacing/layout rhythm: one idea per cell, short paragraphs, and regular section breaks
- Shape/radius/elevation: reuse existing notebook cell cards and restrained rounded corners
- Motion: no new motion; existing hover treatment is sufficient
- Imagery/iconography: use emojis sparingly as semantic signposts, not as section content

## Components

- Existing components to reuse: MkDocs notebook rendering, admonitions, notebook cell cards, built-in `MeasurementSession` display, Polars tables, and PyTestLab plotting helpers
- New/changed components: none; the overhaul is content and notebook-structure only
- Variants and states: simulation-first code path, hardware adaptation note, validation assertions, and export verification
- Token/component ownership: existing theme and `docs/en/stylesheets/notebook-enhancements.css`

## Accessibility

- Target standard: readable Markdown structure and existing theme accessibility conventions
- Keyboard/focus behavior: inherit the documentation theme
- Contrast/readability: avoid low-contrast inline HTML and long unbroken lines; keep code and prose in their native cells
- Screen-reader semantics: use headings, lists, tables, and code fences semantically
- Reduced motion and sensory considerations: no new animation or decorative media

## Responsive behavior

- Supported breakpoints/devices: inherit the existing MkDocs theme's desktop, tablet, and mobile layouts
- Layout adaptations: keep cells and tables within the existing responsive notebook container
- Touch/hover differences: no new interactions

## Interaction states

- Loading: notebook conversion may take time for plotting or notebooks; avoid execution-dependent prose
- Empty: explain that a session requires parameters and an acquisition function
- Error: include cleanup and validation patterns that make failures understandable
- Success: show row counts, summary data, a plot, and a reloaded artifact
- Disabled: simulation mode is the safe default when hardware is unavailable
- Offline/slow network, if applicable: the tutorial must run from the local package and simulation profiles

## Content voice

- Tone: direct, encouraging, and technically specific
- Terminology: use `MeasurementSession`, `Experiment`, parameter sweep, acquisition function, simulation mode, and hardware mode consistently
- Microcopy rules: state the reason before the code; explain output fields; avoid generic congratulations and unsupported installation claims

## Implementation constraints

- Framework/styling system: Jupyter Notebook JSON rendered by MkDocs with `mkdocs-jupyter`
- Design-token constraints: reuse existing theme variables and notebook CSS; do not add a new CSS system for one tutorial
- Performance constraints: no network calls, hardware discovery, or long-running acquisition in the default path
- Compatibility constraints: follow `pyproject.toml`'s Python >=3.11 requirement and current public APIs
- Test/screenshot expectations: execute all code cells, rebuild MkDocs, and verify the tutorial route returns successfully

## Open questions

- [ ] Should future tutorials share a small set of reusable notebook helper snippets? / docs maintainers / medium impact
