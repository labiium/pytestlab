#!/usr/bin/env python3
"""
PyTestLab Notebook Normalization Utility
========================================

A utility to normalize Jupyter notebooks by adding missing cell IDs and
ensuring compliance with current nbformat standards.

This script addresses the MissingIDFieldWarning that occurs when notebooks
don't have unique IDs for each cell.

Features:
- Adds unique IDs to cells missing them
- Preserves existing IDs when present
- Validates notebook structure
- Supports batch processing of multiple notebooks
- Creates backups before modification

Usage:
    python scripts/normalize_notebooks.py --notebook path/to/notebook.ipynb
    python scripts/normalize_notebooks.py --directory docs/en/tutorials/
    python scripts/normalize_notebooks.py --all
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import nbformat
    from nbformat.validator import normalize
    NBFORMAT_AVAILABLE = True
except ImportError:
    NBFORMAT_AVAILABLE = False
    print("Warning: nbformat library not available. Install with: pip install nbformat")


class NotebookNormalizer:
    """
    Normalize Jupyter notebooks to comply with current nbformat standards.

    This class handles adding missing cell IDs, validating structure,
    and ensuring notebooks are compatible with modern Jupyter tools.
    """

    def __init__(self, backup: bool = True, verbose: bool = False):
        """
        Initialize the notebook normalizer.

        Args:
            backup: Whether to create backup files before modification
            verbose: Whether to print detailed progress information
        """
        self.backup = backup
        self.verbose = verbose
        self.processed_count = 0
        self.modified_count = 0

    def log(self, message: str) -> None:
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(message)

    def generate_cell_id(self) -> str:
        """
        Generate a unique cell ID in the format used by Jupyter.

        Returns:
            A unique cell ID string
        """
        # Generate a UUID4 and take the first 8 characters for readability
        return str(uuid.uuid4())[:8]

    def normalize_cell(self, cell: Dict, nbformat_version: int = 4) -> bool:
        """
        Normalize a single cell by adding missing ID if needed.

        Args:
            cell: Cell dictionary from notebook
            nbformat_version: Notebook format version

        Returns:
            True if the cell was modified, False otherwise
        """
        # Only add IDs for nbformat 4.5+
        if nbformat_version >= 4 and ('id' not in cell or not cell['id']):
            # Generate a meaningful ID based on cell type and content
            cell_id = self.generate_meaningful_id(cell)
            cell['id'] = cell_id
            self.log(f"  Added ID '{cell_id}' to {cell.get('cell_type', 'unknown')} cell")
            return True
        return False

    def generate_meaningful_id(self, cell: Dict) -> str:
        """
        Generate a meaningful ID based on cell content.

        Args:
            cell: Cell dictionary

        Returns:
            A descriptive cell ID
        """
        cell_type = cell.get('cell_type', 'unknown')

        if cell_type == 'markdown':
            # For markdown cells, try to use the first heading
            source = self.get_cell_source(cell)
            if source.startswith('#'):
                # Extract heading text and create ID
                heading = source.split('\n')[0].strip('#').strip()
                heading_id = ''.join(c for c in heading.lower().replace(' ', '-')
                                   if c.isalnum() or c == '-')[:20]
                if heading_id:
                    return f"md-{heading_id}"
            return f"md-{self.generate_cell_id()}"

        elif cell_type == 'code':
            # For code cells, try to identify the content type
            source = self.get_cell_source(cell)

            # Check for common patterns
            if 'import' in source[:100]:
                return f"imports-{self.generate_cell_id()}"
            elif 'def ' in source[:100]:
                return f"function-{self.generate_cell_id()}"
            elif 'class ' in source[:100]:
                return f"class-{self.generate_cell_id()}"
            elif source.strip().startswith('#'):
                # Comment-based identification
                comment = source.split('\n')[0].strip('# ').lower()
                comment_id = ''.join(c for c in comment.replace(' ', '-')
                                   if c.isalnum() or c == '-')[:20]
                if comment_id:
                    return f"code-{comment_id}"

            return f"code-{self.generate_cell_id()}"

        else:
            return f"{cell_type}-{self.generate_cell_id()}"

    def get_cell_source(self, cell: Dict) -> str:
        """
        Extract source text from a cell, handling different formats.

        Args:
            cell: Cell dictionary

        Returns:
            Source text as a string
        """
        source = cell.get('source', '')
        if isinstance(source, list):
            return ''.join(source)
        return str(source)

    def normalize_notebook(self, notebook_path: Path) -> bool:
        """
        Normalize a single notebook file.

        Args:
            notebook_path: Path to the notebook file

        Returns:
            True if the notebook was modified, False otherwise
        """
        self.log(f"Processing: {notebook_path}")

        if not NBFORMAT_AVAILABLE:
            print("Error: nbformat library required for normalization")
            return False

        try:
            # Read the notebook using nbformat
            notebook = nbformat.read(notebook_path, as_version=nbformat.NO_CONVERT)

            # Create backup if requested
            if self.backup:
                backup_path = notebook_path.with_suffix('.ipynb.bak')
                shutil.copy2(notebook_path, backup_path)
                self.log(f"  Created backup: {backup_path}")

            # Check if normalization is needed
            original_content = str(notebook)

            # Normalize the notebook (this adds missing IDs)
            normalize(notebook)

            # Check if anything changed
            normalized_content = str(notebook)
            modified = original_content != normalized_content

            # Save if modified
            if modified:
                nbformat.write(notebook, notebook_path)
                self.log(f"  ✅ Normalized and saved: {notebook_path}")
                self.modified_count += 1
            else:
                self.log(f"  ✓ No changes needed: {notebook_path}")

            self.processed_count += 1
            return modified

        except Exception as e:
            print(f"Error processing {notebook_path}: {e}")
            return False

    def normalize_directory(self, directory_path: Path, recursive: bool = True) -> int:
        """
        Normalize all notebooks in a directory.

        Args:
            directory_path: Path to the directory
            recursive: Whether to search subdirectories

        Returns:
            Number of notebooks modified
        """
        if not directory_path.is_dir():
            print(f"Error: {directory_path} is not a directory")
            return 0

        pattern = "**/*.ipynb" if recursive else "*.ipynb"
        notebook_files = list(directory_path.glob(pattern))

        if not notebook_files:
            print(f"No notebook files found in {directory_path}")
            return 0

        print(f"Found {len(notebook_files)} notebook(s) in {directory_path}")

        initial_modified = self.modified_count
        for notebook_path in notebook_files:
            self.normalize_notebook(notebook_path)

        return self.modified_count - initial_modified

    def validate_notebook(self, notebook_path: Path) -> bool:
        """
        Validate that a notebook has all required fields.

        Args:
            notebook_path: Path to the notebook file

        Returns:
            True if the notebook is valid, False otherwise
        """
        if not NBFORMAT_AVAILABLE:
            print("Error: nbformat library required for validation")
            return False

        try:
            # Read and validate using nbformat
            notebook = nbformat.read(notebook_path, as_version=nbformat.NO_CONVERT)
            nbformat.validate(notebook)

            print(f"✅ {notebook_path}: Valid notebook structure")
            return True

        except nbformat.ValidationError as e:
            print(f"❌ {notebook_path}: Validation error - {e}")
            return False
        except Exception as e:
            print(f"❌ {notebook_path}: Error reading notebook - {e}")
            return False


def main():
    """Main CLI interface for notebook normalization."""
    parser = argparse.ArgumentParser(
        description="Normalize Jupyter notebooks by adding missing cell IDs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/normalize_notebooks.py --notebook docs/en/tutorials/example.ipynb
  python scripts/normalize_notebooks.py --directory docs/en/tutorials/ --verbose
  python scripts/normalize_notebooks.py --all --no-backup
  python scripts/normalize_notebooks.py --validate docs/en/tutorials/
        """
    )

    parser.add_argument(
        "--notebook",
        type=Path,
        help="Path to a specific notebook file to normalize"
    )

    parser.add_argument(
        "--directory",
        type=Path,
        help="Path to a directory containing notebooks to normalize"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Normalize all notebooks in the docs directory"
    )

    parser.add_argument(
        "--validate",
        type=Path,
        help="Validate notebook(s) without modifying them"
    )

    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't create backup files before modification"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed progress information"
    )

    parser.add_argument(
        "--recursive",
        action="store_true",
        default=True,
        help="Search subdirectories recursively (default: True)"
    )

    args = parser.parse_args()

    # Validate arguments
    if not any([args.notebook, args.directory, args.all, args.validate]):
        parser.error("Must specify --notebook, --directory, --all, or --validate")

    # Initialize normalizer
    normalizer = NotebookNormalizer(
        backup=not args.no_backup,
        verbose=args.verbose
    )

    try:
        if args.validate:
            # Validation mode
            if args.validate.is_file():
                normalizer.validate_notebook(args.validate)
            elif args.validate.is_dir():
                pattern = "**/*.ipynb" if args.recursive else "*.ipynb"
                notebooks = list(args.validate.glob(pattern))
                print(f"Validating {len(notebooks)} notebook(s)...")
                for notebook_path in notebooks:
                    normalizer.validate_notebook(notebook_path)
            else:
                print(f"Error: {args.validate} does not exist")
                sys.exit(1)

        elif args.notebook:
            # Single notebook
            if not args.notebook.exists():
                print(f"Error: {args.notebook} does not exist")
                sys.exit(1)

            normalizer.normalize_notebook(args.notebook)

        elif args.directory:
            # Directory of notebooks
            normalizer.normalize_directory(args.directory, args.recursive)

        elif args.all:
            # All notebooks in docs
            docs_path = Path("docs/en")
            if not docs_path.exists():
                # Try alternative path
                docs_path = Path("en")
                if not docs_path.exists():
                    print("Error: Could not find docs directory")
                    sys.exit(1)

            normalizer.normalize_directory(docs_path, recursive=True)

        # Print summary
        if not args.validate:
            print(f"\n📊 Summary:")
            print(f"  Processed: {normalizer.processed_count} notebook(s)")
            print(f"  Modified: {normalizer.modified_count} notebook(s)")

            if normalizer.modified_count > 0:
                print("✅ Notebook normalization completed successfully!")
            else:
                print("✓ All notebooks were already normalized.")

    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
