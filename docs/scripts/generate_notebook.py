#!/usr/bin/env python3
"""
PyTestLab Notebook Generation Utility
=====================================

A utility for generating professional, consistently styled Jupyter notebooks
that match the PyTestLab documentation theme and branding.

Features:
- Professional notebook structure with metadata
- Consistent cell styling and formatting
- Auto-generated headers and footers
- Code syntax highlighting optimization
- Integration with PyTestLab branding
- Support for different notebook types (tutorial, example, documentation)

Usage:
    python docs/scripts/generate_notebook.py --type tutorial --title "My Tutorial" --output en/tutorials/my_tutorial.ipynb
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union


class NotebookGenerator:
    """
    Professional Jupyter notebook generator for PyTestLab documentation.

    Generates notebooks with consistent styling, metadata, and structure
    that integrates seamlessly with the PyTestLab documentation theme.
    """

    # Notebook templates for different types
    TEMPLATES = {
        "tutorial": {
            "title_prefix": "PyTestLab Tutorial:",
            "description": "Learn how to use PyTestLab effectively with this hands-on tutorial.",
            "tags": ["tutorial", "pytestlab", "measurement", "automation"],
            "category": "educational"
        },
        "example": {
            "title_prefix": "PyTestLab Example:",
            "description": "Practical example demonstrating PyTestLab capabilities.",
            "tags": ["example", "pytestlab", "demo", "practical"],
            "category": "demonstration"
        },
        "documentation": {
            "title_prefix": "PyTestLab Documentation:",
            "description": "Technical documentation and reference material.",
            "tags": ["documentation", "pytestlab", "reference", "technical"],
            "category": "reference"
        },
        "guide": {
            "title_prefix": "PyTestLab Guide:",
            "description": "Step-by-step guide for specific PyTestLab workflows.",
            "tags": ["guide", "pytestlab", "workflow", "how-to"],
            "category": "instructional"
        }
    }

    def __init__(self):
        """Initialize the notebook generator."""
        self.notebook_version = "4.5"
        self.python_version = "3.9+"

    def create_metadata(self, notebook_type: str, title: str, author: str = "LABIIUM") -> Dict:
        """
        Create comprehensive notebook metadata.

        Args:
            notebook_type: Type of notebook (tutorial, example, etc.)
            title: Title of the notebook
            author: Author name

        Returns:
            Complete metadata dictionary
        """
        template = self.TEMPLATES.get(notebook_type, self.TEMPLATES["tutorial"])

        return {
            "kernelspec": {
                "display_name": "Python 3 (PyTestLab)",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": self.python_version
            },
            "toc": {
                "base_numbering": 1,
                "nav_menu": {},
                "number_sections": True,
                "sideBar": True,
                "skip_h1_title": False,
                "title_cell": "Table of Contents",
                "title_sidebar": "Contents",
                "toc_cell": False,
                "toc_position": {},
                "toc_section_display": True,
                "toc_window_display": False
            },
            "pytestlab": {
                "version": "latest",
                "notebook_type": notebook_type,
                "category": template["category"],
                "tags": template["tags"],
                "created": datetime.now().isoformat(),
                "author": author,
                "license": "MIT",
                "repository": "https://github.com/labiium/pytestlab"
            }
        }

    def create_title_cell(self, notebook_type: str, title: str, description: Optional[str] = None) -> Dict:
        """
        Create a professional title cell with PyTestLab branding.

        Args:
            notebook_type: Type of notebook
            title: Main title
            description: Optional description

        Returns:
            Markdown cell dictionary
        """
        template = self.TEMPLATES.get(notebook_type, self.TEMPLATES["tutorial"])
        full_title = f"{template['title_prefix']} {title}"

        if description is None:
            description = template["description"]

        markdown_content = f"""# {full_title}

<div style="background: linear-gradient(135deg, #5333ed 0%, #04e2dc 100%); padding: 1.5rem; border-radius: 12px; margin: 1rem 0; color: white;">
    <h2 style="margin: 0 0 0.5rem 0; color: white;">✨ PyTestLab Professional Notebook</h2>
    <p style="margin: 0; opacity: 0.9; font-size: 1.1rem;">{description}</p>
</div>

---

## 📋 Overview

This notebook demonstrates PyTestLab's capabilities in a professional, reproducible manner. Each code cell is designed to be educational and immediately executable.

### 🎯 Learning Objectives

- Understand core PyTestLab concepts
- Learn best practices for measurement automation
- Explore practical implementation patterns
- Build confidence with hands-on examples

### 📚 Prerequisites

- Python {self.python_version} or higher
- PyTestLab installed (`pip install pytestlab`)
- Basic understanding of Python programming
- Optional: Hardware instruments for real measurements

---
"""

        return {
            "cell_type": "markdown",
            "metadata": {
                "tags": ["title", "header"]
            },
            "source": markdown_content.split('\n')
        }

    def create_setup_cell(self, imports: Optional[List[str]] = None) -> Dict:
        """
        Create a standardized setup cell with common imports.

        Args:
            imports: Additional imports to include

        Returns:
            Code cell dictionary
        """
        standard_imports = [
            "# Standard library imports",
            "import sys",
            "import os",
            "from pathlib import Path",
            "from typing import List, Dict, Optional, Union",
            "",
            "# Scientific computing",
            "import numpy as np",
            "import polars as pl",
            "",
            "# PyTestLab core imports",
            "from pytestlab.instruments import AutoInstrument",
            "from pytestlab.measurements import MeasurementSession",
            "from pytestlab.experiments import Experiment",
            "",
            "# Display and visualization",
            "from IPython.display import display, HTML, Markdown",
            "import matplotlib.pyplot as plt",
            "plt.style.use('seaborn-v0_8-whitegrid')",
            "",
            "# Configure notebook for optimal display",
            "plt.rcParams['figure.figsize'] = (10, 6)",
            "plt.rcParams['font.size'] = 12",
            "np.set_printoptions(precision=4, suppress=True)",
            "",
            "print('🚀 PyTestLab environment initialized successfully!')",
            "print(f'📍 Working directory: {os.getcwd()}')",
            "print(f'🐍 Python version: {sys.version.split()[0]}')"
        ]

        if imports:
            standard_imports.extend(["", "# Additional imports"] + imports)

        return {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {
                "tags": ["setup", "imports"],
                "collapse": False
            },
            "outputs": [],
            "source": standard_imports
        }

    def create_section_cell(self, section_number: int, title: str, description: str = "") -> Dict:
        """
        Create a section header cell with consistent formatting.

        Args:
            section_number: Section number
            title: Section title
            description: Optional description

        Returns:
            Markdown cell dictionary
        """
        markdown_content = f"""## {section_number}. {title}

{description}

---
"""

        return {
            "cell_type": "markdown",
            "metadata": {
                "tags": ["section", f"section-{section_number}"]
            },
            "source": markdown_content.split('\n')
        }

    def create_code_cell(self, code: Union[str, List[str]], description: str = "",
                        execution_count: Optional[int] = None, outputs: Optional[List] = None) -> Dict:
        """
        Create a code cell with optional description and outputs.

        Args:
            code: Code content as string or list of lines
            description: Optional description comment
            execution_count: Optional execution count
            outputs: Optional outputs list

        Returns:
            Code cell dictionary
        """
        if isinstance(code, str):
            code_lines = code.split('\n')
        else:
            code_lines = code

        if description:
            code_lines = [f"# {description}", ""] + code_lines

        return {
            "cell_type": "code",
            "execution_count": execution_count,
            "metadata": {
                "tags": ["code"]
            },
            "outputs": outputs or [],
            "source": code_lines
        }

    def create_markdown_cell(self, content: Union[str, List[str]],
                           cell_type: str = "content") -> Dict:
        """
        Create a markdown cell with content.

        Args:
            content: Markdown content as string or list of lines
            cell_type: Type tag for the cell

        Returns:
            Markdown cell dictionary
        """
        if isinstance(content, str):
            content_lines = content.split('\n')
        else:
            content_lines = content

        return {
            "cell_type": "markdown",
            "metadata": {
                "tags": ["markdown", cell_type]
            },
            "source": content_lines
        }

    def create_conclusion_cell(self, notebook_type: str) -> Dict:
        """
        Create a professional conclusion cell with next steps.

        Args:
            notebook_type: Type of notebook

        Returns:
            Markdown cell dictionary
        """
        markdown_content = """## 🎉 Conclusion

Congratulations! You've successfully completed this PyTestLab notebook.

### 📈 What You've Learned

- Core PyTestLab concepts and patterns
- Best practices for measurement automation
- Professional notebook development techniques
- Integration with modern Python scientific stack

### 🚀 Next Steps

1. **Explore More Examples**: Check out other PyTestLab notebooks in the documentation
2. **Build Your Own**: Create custom measurement workflows for your specific needs
3. **Contribute**: Share your improvements and examples with the community
4. **Connect**: Join the PyTestLab community for support and collaboration

### 📚 Additional Resources

- 📖 [PyTestLab Documentation](https://pytestlab.readthedocs.io/)
- 💻 [GitHub Repository](https://github.com/labiium/pytestlab)
- 🎓 [Tutorials and Guides](https://pytestlab.readthedocs.io/tutorials/)
- 💬 [Community Discussions](https://github.com/labiium/pytestlab/discussions)

---

<div style="background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); border-left: 4px solid #5333ed; padding: 1rem; margin: 1rem 0; border-radius: 8px;">
    <h4 style="margin: 0 0 0.5rem 0; color: #5333ed;">💡 Pro Tip</h4>
    <p style="margin: 0; color: #374151;">
        Save this notebook as a template for your own PyTestLab projects.
        The structure and patterns demonstrated here follow industry best practices
        for reproducible scientific computing.
    </p>
</div>

**Happy Measuring!** 🔬✨
"""

        return {
            "cell_type": "markdown",
            "metadata": {
                "tags": ["conclusion", "footer"]
            },
            "source": markdown_content.split('\n')
        }

    def generate_notebook(self, notebook_type: str, title: str, output_path: Path,
                         sections: Optional[List[Dict]] = None,
                         author: str = "LABIIUM",
                         additional_imports: Optional[List[str]] = None) -> Dict:
        """
        Generate a complete professional notebook.

        Args:
            notebook_type: Type of notebook to generate
            title: Main title of the notebook
            output_path: Path where to save the notebook
            sections: Optional list of section definitions
            author: Author name
            additional_imports: Additional imports for setup cell

        Returns:
            Complete notebook dictionary
        """
        cells = []

        # Title and header
        cells.append(self.create_title_cell(notebook_type, title))

        # Setup cell
        cells.append(self.create_setup_cell(additional_imports))

        # Add custom sections or default structure
        if sections:
            for i, section in enumerate(sections, 1):
                cells.append(self.create_section_cell(
                    i, section["title"], section.get("description", "")
                ))

                if "content" in section:
                    if section["content"]["type"] == "code":
                        cells.append(self.create_code_cell(
                            section["content"]["source"],
                            section["content"].get("description", "")
                        ))
                    elif section["content"]["type"] == "markdown":
                        cells.append(self.create_markdown_cell(
                            section["content"]["source"]
                        ))
        else:
            # Default structure for tutorials
            cells.append(self.create_section_cell(
                1, "Basic Setup",
                "Let's start with the fundamental PyTestLab setup and configuration."
            ))

            cells.append(self.create_code_cell([
                "# Connect to a simulated instrument for demonstration",
                "instrument = AutoInstrument.from_config('generic/dmm', backend='sim')",
                "",
                "# Verify connection",
                "print(f'Connected to: {instrument.id()}')",
                "print(f'Instrument type: {type(instrument).__name__}')"
            ], "Connect to a simulated instrument"))

            cells.append(self.create_section_cell(
                2, "Basic Operations",
                "Explore basic instrument operations and measurement capabilities."
            ))

            cells.append(self.create_code_cell([
                "# Perform a basic measurement",
                "try:",
                "    measurement = instrument.measure()",
                "    print(f'Measurement result: {measurement}')",
                "except Exception as e:",
                "    print(f'Measurement error: {e}')",
                "",
                "# Clean up",
                "instrument.close()",
                "print('✅ Instrument disconnected successfully')"
            ], "Perform basic measurement and cleanup"))

        # Conclusion
        cells.append(self.create_conclusion_cell(notebook_type))

        # Complete notebook structure
        notebook = {
            "cells": cells,
            "metadata": self.create_metadata(notebook_type, title, author),
            "nbformat": 4,
            "nbformat_minor": 5
        }

        return notebook

    def save_notebook(self, notebook: Dict, output_path: Path) -> None:
        """
        Save notebook to file with proper formatting.

        Args:
            notebook: Complete notebook dictionary
            output_path: Path to save the notebook
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(notebook, f, indent=2, ensure_ascii=False)

        print(f"✅ Notebook saved to: {output_path}")
        print(f"📊 Created {len(notebook['cells'])} cells")
        print(f"🏷️  Type: {notebook['metadata']['pytestlab']['notebook_type']}")


def main():
    """Main CLI interface for notebook generation."""
    parser = argparse.ArgumentParser(
        description="Generate professional PyTestLab Jupyter notebooks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python docs/scripts/generate_notebook.py --type tutorial --title "Getting Started" --output en/tutorials/getting_started.ipynb
  python docs/scripts/generate_notebook.py --type example --title "DMM Measurements" --output en/tutorials/dmm_example.ipynb --author "Your Name"
        """
    )

    parser.add_argument(
        "--type",
        choices=list(NotebookGenerator.TEMPLATES.keys()),
        default="tutorial",
        help="Type of notebook to generate"
    )

    parser.add_argument(
        "--title",
        required=True,
        help="Title of the notebook"
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for the notebook file"
    )

    parser.add_argument(
        "--author",
        default="LABIIUM",
        help="Author name for the notebook metadata"
    )

    parser.add_argument(
        "--description",
        help="Custom description for the notebook"
    )

    parser.add_argument(
        "--imports",
        nargs="*",
        help="Additional import statements to include in setup cell"
    )

    args = parser.parse_args()

    try:
        generator = NotebookGenerator()

        print(f"🚀 Generating {args.type} notebook: '{args.title}'")
        print(f"📁 Output: {args.output}")

        notebook = generator.generate_notebook(
            notebook_type=args.type,
            title=args.title,
            output_path=args.output,
            author=args.author,
            additional_imports=args.imports
        )

        generator.save_notebook(notebook, args.output)

        print("\n🎉 Notebook generation completed successfully!")
        print(f"💡 You can now open the notebook in Jupyter Lab/Notebook or VS Code")

    except Exception as e:
        print(f"❌ Error generating notebook: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
