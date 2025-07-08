# Contributing to PyTestLab

Thank you for your interest in contributing to PyTestLab! Your help makes this project better for everyone in the scientific and engineering community.

This guide explains how to get started, the development workflow, and best practices for contributing code, documentation, and ideas.

---

## Code of Conduct

All contributors are expected to follow the [PyTestLab Code of Conduct](CODE_OF_CONDUCT.md). Please help us keep the community welcoming and inclusive.

---

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:
    ```bash
    git clone https://github.com/YOUR_USERNAME/pytestlab.git
    cd pytestlab
    ```
3. **Set up a virtual environment** (recommended):
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```
4. **Install dependencies** (including development tools):
    ```bash
    pip install -e .[dev,full]
    ```
5. **Install pre-commit hooks** (for linting and formatting):
    ```bash
    pre-commit install
    ```

---

## Development Workflow

- **Create a feature branch** for your work:
    ```bash
    git checkout -b feat/short-description
    ```
- **Make your changes** (code, docs, or tests).
- **Add or update tests** to cover your changes.
- **Run the test suite**:
    ```bash
    pytest
    ```
- **Run pre-commit checks** (these will also run automatically on commit):
    ```bash
    pre-commit run --all-files
    ```
- **Commit using Conventional Commits** (enforced by commitizen):
    ```bash
    cz c
    ```
- **Push your branch** to your fork:
    ```bash
    git push origin feat/short-description
    ```
- **Open a Pull Request** against the `main` branch on GitHub.

---

## Code Style & Quality

- **Linting & Formatting:** PyTestLab uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [Black](https://black.readthedocs.io/) for code style. These are enforced by pre-commit.
- **Type Checking:** Use [MyPy](http://mypy-lang.org/) for static type checking.
- **Commit Messages:** Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification. Use `cz c` to help format your commit messages.

---

## Documentation

- **Docs live in `docs/`** and are written in Markdown or Jupyter Notebooks.
- **API docs** are generated using [mkdocstrings](https://mkdocstrings.github.io/).
- **To preview docs locally:**
    ```bash
    mkdocs serve
    ```
- **Update or add docstrings** to your code as needed.

---

## Tests

- **Unit tests** live in the `tests/` directory.
- **All new features and bugfixes must include tests.**
- **Run the full test suite before submitting a PR.**

---

## Submitting a Pull Request

- Ensure your branch is up to date with `main`.
- Provide a clear title and description for your PR.
- Link to any relevant issues.
- Be responsive to code review feedback.

---

## Need Help?

- **Bugs & Feature Requests:** Open an issue on GitHub.
- **Questions:** Use GitHub Discussions or reach out via the project chat (see the README for links).
- **Security Issues:** Please report security vulnerabilities privately to the maintainers.

---

Thank you for helping make PyTestLab better!