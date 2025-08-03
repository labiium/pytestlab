#!/usr/bin/env python3
"""
PyTestLab Notebook Styling Validation Script
============================================

This script validates that the notebook styling enhancements are properly
implemented and working correctly in the PyTestLab documentation.

Features:
- Validates CSS file existence and structure
- Checks JavaScript functionality
- Verifies notebook structure and metadata
- Tests responsive design elements
- Validates accessibility features

Usage:
    python scripts/validate_styling.py
    python scripts/validate_styling.py --verbose
    python scripts/validate_styling.py --check-all
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class NotebookStylingValidator:
    """
    Validator for PyTestLab notebook styling implementation.

    Checks CSS, JavaScript, HTML structure, and accessibility compliance.
    """

    def __init__(self, verbose: bool = False):
        """Initialize the validator."""
        self.verbose = verbose
        self.passed_tests = 0
        self.failed_tests = 0
        self.warnings = 0

        # Base paths
        self.docs_path = Path("en")
        self.css_path = self.docs_path / "stylesheets"
        self.js_path = self.docs_path / "js"
        self.notebooks_path = self.docs_path / "tutorials"

    def log(self, message: str, level: str = "INFO") -> None:
        """Log a message if verbose mode is enabled."""
        if self.verbose or level in ["ERROR", "WARNING"]:
            prefix = {
                "INFO": "ℹ️ ",
                "SUCCESS": "✅",
                "WARNING": "⚠️ ",
                "ERROR": "❌"
            }.get(level, "")
            print(f"{prefix} {message}")

    def test_css_files(self) -> bool:
        """Test that required CSS files exist and have correct content."""
        self.log("Testing CSS files...", "INFO")

        # Check if main enhancement CSS exists
        main_css = self.css_path / "notebook-enhancements.css"
        if not main_css.exists():
            self.log(f"Main CSS file missing: {main_css}", "ERROR")
            return False

        # Read and validate CSS content
        css_content = main_css.read_text(encoding='utf-8')

        # Check for key CSS classes and variables
        required_elements = [
            ":root",
            "--lab-violet",
            "--lab-aqua",
            "--photon-white",
            ".jp-Cell",
            ".nb-cell",
            ".copy-button",
            ".jp-InputArea",
            ".jp-OutputArea",
            "glassmorphism"
        ]

        missing_elements = []
        for element in required_elements:
            if element not in css_content:
                missing_elements.append(element)

        if missing_elements:
            self.log(f"Missing CSS elements: {missing_elements}", "ERROR")
            return False

        # Check for responsive design
        if "@media" not in css_content:
            self.log("No responsive design breakpoints found", "WARNING")
            self.warnings += 1

        # Check for accessibility features
        accessibility_features = [
            "prefers-reduced-motion",
            "prefers-contrast",
            "focus-within",
            "aria-"
        ]

        found_accessibility = sum(1 for feature in accessibility_features if feature in css_content)
        if found_accessibility < 2:
            self.log("Limited accessibility features in CSS", "WARNING")
            self.warnings += 1

        self.log("CSS files validation passed", "SUCCESS")
        return True

    def test_javascript_files(self) -> bool:
        """Test that JavaScript enhancement files exist and are properly structured."""
        self.log("Testing JavaScript files...", "INFO")

        # Check if main JS file exists
        main_js = self.js_path / "notebook-enhancements.js"
        if not main_js.exists():
            self.log(f"Main JavaScript file missing: {main_js}", "ERROR")
            return False

        # Read and validate JavaScript content
        js_content = main_js.read_text(encoding='utf-8')

        # Check for key functions and features
        required_features = [
            "copyToClipboard",
            "cellEnhancements",
            "syntaxEnhancements",
            "responsiveEnhancements",
            "addEventListener",
            "querySelector",
            "clipboard"
        ]

        missing_features = []
        for feature in required_features:
            if feature not in js_content:
                missing_features.append(feature)

        if missing_features:
            self.log(f"Missing JavaScript features: {missing_features}", "ERROR")
            return False

        # Check for error handling
        if "try" not in js_content or "catch" not in js_content:
            self.log("Limited error handling in JavaScript", "WARNING")
            self.warnings += 1

        # Check for browser compatibility
        if "navigator.clipboard" not in js_content:
            self.log("Missing modern clipboard API", "WARNING")
            self.warnings += 1

        self.log("JavaScript files validation passed", "SUCCESS")
        return True

    def test_mkdocs_config(self) -> bool:
        """Test that mkdocs.yml is properly configured for the enhancements."""
        self.log("Testing MkDocs configuration...", "INFO")

        mkdocs_config = Path("mkdocs.yml")
        if not mkdocs_config.exists():
            self.log("MkDocs config file not found", "ERROR")
            return False

        config_content = mkdocs_config.read_text(encoding='utf-8')

        # Check for required plugins
        required_plugins = [
            "mkdocs-jupyter",
            "awesome-pages"
        ]

        missing_plugins = []
        for plugin in required_plugins:
            if plugin not in config_content:
                missing_plugins.append(plugin)

        if missing_plugins:
            self.log(f"Missing MkDocs plugins: {missing_plugins}", "ERROR")
            return False

        # Check for CSS and JS files in config
        if "notebook-enhancements.css" not in config_content:
            self.log("Enhanced CSS not included in config", "ERROR")
            return False

        if "notebook-enhancements.js" not in config_content:
            self.log("Enhanced JavaScript not included in config", "ERROR")
            return False

        self.log("MkDocs configuration validation passed", "SUCCESS")
        return True

    def test_notebook_structure(self) -> bool:
        """Test that notebooks have proper structure and metadata."""
        self.log("Testing notebook structure...", "INFO")

        if not self.notebooks_path.exists():
            self.log("Notebooks directory not found", "ERROR")
            return False

        notebook_files = list(self.notebooks_path.glob("*.ipynb"))
        if not notebook_files:
            self.log("No notebook files found", "ERROR")
            return False

        structural_issues = []

        for notebook_path in notebook_files[:3]:  # Test first 3 notebooks
            try:
                with open(notebook_path, 'r', encoding='utf-8') as f:
                    notebook = json.load(f)

                # Check basic structure
                if 'cells' not in notebook:
                    structural_issues.append(f"{notebook_path.name}: Missing cells")

                if 'metadata' not in notebook:
                    structural_issues.append(f"{notebook_path.name}: Missing metadata")

                # Check for professional structure
                cells = notebook.get('cells', [])
                if cells:
                    first_cell = cells[0]
                    if first_cell.get('cell_type') != 'markdown':
                        structural_issues.append(f"{notebook_path.name}: Should start with markdown title")

                # Check for proper cell metadata
                has_tagged_cells = any(
                    cell.get('metadata', {}).get('tags')
                    for cell in cells
                )

                if not has_tagged_cells:
                    self.log(f"{notebook_path.name}: No tagged cells found", "WARNING")
                    self.warnings += 1

            except json.JSONDecodeError:
                structural_issues.append(f"{notebook_path.name}: Invalid JSON")
            except Exception as e:
                structural_issues.append(f"{notebook_path.name}: {str(e)}")

        if structural_issues:
            self.log(f"Notebook structural issues: {structural_issues}", "ERROR")
            return False

        self.log("Notebook structure validation passed", "SUCCESS")
        return True

    def test_color_scheme(self) -> bool:
        """Test that the color scheme is properly implemented."""
        self.log("Testing color scheme...", "INFO")

        css_file = self.css_path / "notebook-enhancements.css"
        if not css_file.exists():
            return False

        css_content = css_file.read_text(encoding='utf-8')

        # Check for required color variables
        required_colors = [
            "--lab-violet: #5333ed",
            "--lab-aqua: #04e2dc",
            "--photon-white: #f5f7fa",
            "--photon-black: #0b0e11"
        ]

        missing_colors = []
        for color in required_colors:
            if color not in css_content:
                missing_colors.append(color)

        if missing_colors:
            self.log(f"Missing color definitions: {missing_colors}", "ERROR")
            return False

        # Check for gradient usage
        if "linear-gradient" not in css_content:
            self.log("No gradient effects found", "WARNING")
            self.warnings += 1

        self.log("Color scheme validation passed", "SUCCESS")
        return True

    def test_responsive_design(self) -> bool:
        """Test responsive design implementation."""
        self.log("Testing responsive design...", "INFO")

        css_file = self.css_path / "notebook-enhancements.css"
        if not css_file.exists():
            return False

        css_content = css_file.read_text(encoding='utf-8')

        # Check for media queries
        media_queries = re.findall(r'@media[^{]+{', css_content)

        if len(media_queries) < 2:
            self.log("Insufficient responsive breakpoints", "ERROR")
            return False

        # Check for mobile-specific styles
        if "max-width: 768px" not in css_content:
            self.log("No mobile breakpoint found", "WARNING")
            self.warnings += 1

        # Check for print styles
        if "@media print" not in css_content:
            self.log("No print styles found", "WARNING")
            self.warnings += 1

        self.log("Responsive design validation passed", "SUCCESS")
        return True

    def test_accessibility_features(self) -> bool:
        """Test accessibility features implementation."""
        self.log("Testing accessibility features...", "INFO")

        css_file = self.css_path / "notebook-enhancements.css"
        js_file = self.js_path / "notebook-enhancements.js"

        if not css_file.exists() or not js_file.exists():
            return False

        css_content = css_file.read_text(encoding='utf-8')
        js_content = js_file.read_text(encoding='utf-8')

        # Check CSS accessibility features
        css_accessibility = [
            "prefers-reduced-motion",
            "prefers-contrast",
            "focus-within",
            ":focus",
            "outline"
        ]

        css_score = sum(1 for feature in css_accessibility if feature in css_content)

        # Check JavaScript accessibility features
        js_accessibility = [
            "aria-label",
            "tabindex",
            "keyboard",
            "focus",
            "role"
        ]

        js_score = sum(1 for feature in js_accessibility if feature in js_content)

        total_score = css_score + js_score

        if total_score < 5:
            self.log(f"Limited accessibility features (score: {total_score}/10)", "ERROR")
            return False
        elif total_score < 8:
            self.log(f"Good accessibility features (score: {total_score}/10)", "WARNING")
            self.warnings += 1

        self.log("Accessibility features validation passed", "SUCCESS")
        return True

    def test_performance_optimizations(self) -> bool:
        """Test performance optimization implementations."""
        self.log("Testing performance optimizations...", "INFO")

        js_file = self.js_path / "notebook-enhancements.js"
        css_file = self.css_path / "notebook-enhancements.css"

        if not js_file.exists() or not css_file.exists():
            return False

        js_content = js_file.read_text(encoding='utf-8')
        css_content = css_file.read_text(encoding='utf-8')

        # Check JavaScript performance features
        js_optimizations = [
            "debounce",
            "IntersectionObserver",
            "requestAnimationFrame",
            "passive"
        ]

        js_score = sum(1 for opt in js_optimizations if opt in js_content)

        # Check CSS performance features
        css_optimizations = [
            "transform",
            "will-change",
            "contain",
            "opacity"
        ]

        css_score = sum(1 for opt in css_optimizations if opt in css_content)

        total_score = js_score + css_score

        if total_score < 3:
            self.log(f"Limited performance optimizations (score: {total_score}/8)", "WARNING")
            self.warnings += 1

        self.log("Performance optimizations validation passed", "SUCCESS")
        return True

    def run_validation(self, check_all: bool = False) -> bool:
        """
        Run the complete validation suite.

        Args:
            check_all: Whether to run all tests including optional ones

        Returns:
            True if all critical tests pass, False otherwise
        """
        self.log("Starting PyTestLab notebook styling validation...", "INFO")

        # Core tests (must pass)
        core_tests = [
            ("CSS Files", self.test_css_files),
            ("JavaScript Files", self.test_javascript_files),
            ("MkDocs Config", self.test_mkdocs_config),
            ("Notebook Structure", self.test_notebook_structure),
            ("Color Scheme", self.test_color_scheme),
        ]

        # Extended tests (warnings only)
        extended_tests = [
            ("Responsive Design", self.test_responsive_design),
            ("Accessibility Features", self.test_accessibility_features),
            ("Performance Optimizations", self.test_performance_optimizations),
        ]

        all_tests = core_tests + (extended_tests if check_all else [])

        # Run tests
        for test_name, test_func in all_tests:
            try:
                if test_func():
                    self.passed_tests += 1
                else:
                    self.failed_tests += 1
                    if test_name in [name for name, _ in core_tests]:
                        self.log(f"Critical test failed: {test_name}", "ERROR")
            except Exception as e:
                self.log(f"Test error in {test_name}: {e}", "ERROR")
                self.failed_tests += 1

        # Print summary
        total_tests = self.passed_tests + self.failed_tests
        self.log("\n" + "="*50, "INFO")
        self.log("VALIDATION SUMMARY", "INFO")
        self.log("="*50, "INFO")
        self.log(f"Tests run: {total_tests}", "INFO")
        self.log(f"Passed: {self.passed_tests}", "SUCCESS")
        self.log(f"Failed: {self.failed_tests}", "ERROR" if self.failed_tests > 0 else "INFO")
        self.log(f"Warnings: {self.warnings}", "WARNING" if self.warnings > 0 else "INFO")

        if self.failed_tests == 0:
            self.log("🎉 All validations passed!", "SUCCESS")
            if self.warnings > 0:
                self.log(f"Note: {self.warnings} warning(s) - consider addressing these for optimal experience", "WARNING")
            return True
        else:
            self.log("❌ Some validations failed. Please review and fix the issues above.", "ERROR")
            return False


def main():
    """Main CLI interface for styling validation."""
    parser = argparse.ArgumentParser(
        description="Validate PyTestLab notebook styling implementation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python docs/scripts/validate_styling.py
  python docs/scripts/validate_styling.py --verbose
  python docs/scripts/validate_styling.py --check-all --verbose
        """
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed validation information"
    )

    parser.add_argument(
        "--check-all",
        action="store_true",
        help="Run all tests including extended validations"
    )

    args = parser.parse_args()

    try:
        validator = NotebookStylingValidator(verbose=args.verbose)
        success = validator.run_validation(check_all=args.check_all)

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n⚠️  Validation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Validation error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
