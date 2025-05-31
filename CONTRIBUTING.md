# Contributing to PyTestLab

First off, thank you for considering contributing to PyTestLab! It's people like you that make PyTestLab such a great tool.

This document provides guidelines for contributing to PyTestLab. Please read it before you start.

## Code of Conduct

This project and everyone participating in it is governed by the [PyTestLab Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to `pytestlab-conduct@example.com`.

## Getting Started

1.  **Fork the repository** on GitHub.
2.  **Clone your fork** locally: `git clone https://github.com/YOUR_USERNAME/pytestlab.git`
3.  **Set up the development environment:**
    *   It's recommended to use a virtual environment:
        ```bash
        python -m venv .venv
        source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
        ```
    *   Install dependencies, including development tools:
        ```bash
        pip install -e .[dev,full] 
        ```
    *   Install pre-commit hooks (this will run linters/formatters before each commit):
        ```bash
        pre-commit install
        ```

## Running Tests

To run the test suite, use pytest:

```bash
pytest
```

Ensure all tests pass before submitting a pull request. New features should include new tests.

## Code Style

*   PyTestLab uses **Ruff** for linting and formatting, and **MyPy** for type checking. These are enforced by pre-commit hooks.
*   Commits should follow the **Conventional Commits** specification (e.g., `feat: add new oscilloscope feature`). `commitizen` (`cz c`) is configured to help with this.

## Submitting Changes

1.  **Create a feature branch:** `git checkout -b name-of-your-feature`
2.  **Make your changes.**
3.  **Add tests** for your changes.
4.  **Ensure all tests pass** (`pytest`).
5.  **Ensure pre-commit checks pass.** If they make changes, `git add` those files and re-commit.
6.  **Commit your changes** using conventional commit messages (`cz c` or `git cz commit`).
7.  **Push your branch** to your fork: `git push origin name-of-your-feature`
8.  **Open a Pull Request (PR)** to the `main` branch of the official PyTestLab repository.
    *   Provide a clear title and description for your PR.
    *   Link to any relevant issues.

## Code Review

*   Maintainers will review your PR.
*   Address any feedback or requested changes.
*   Once approved, your PR will be merged.

## Reporting Issues

*   Use GitHub Issues to report bugs or suggest features.
*   Provide as much detail as possible:
    *   PyTestLab version, Python version, OS.
    *   Steps to reproduce the bug.
    *   Expected behavior and actual behavior.
    *   Relevant logs or tracebacks.

## Suggesting Enhancements

*   For major changes, please open an issue first to discuss your proposal.

## Maintainers

*   (To be listed - e.g., Project Lead, Core Contributors) - For now, this can be a placeholder.

## Roadmap

*   A high-level roadmap may be available in `ROADMAP.md` or in the project documentation. (This can be a placeholder for now).