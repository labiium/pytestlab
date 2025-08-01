#!/usr/bin/env python3
"""
PyTestLab Async-to-Sync Migration Script

This script helps automate the conversion of PyTestLab code from async to sync patterns.
It performs basic transformations and provides warnings for areas that need manual review.

Usage:
    python migrate_async_to_sync.py <input_file> [output_file]

If no output file is specified, changes are made in-place with a backup created.
"""

import argparse
import re
import sys
import shutil
from pathlib import Path
from typing import List, Tuple


class AsyncToSyncMigrator:
    """Migrates PyTestLab async code to synchronous patterns."""

    def __init__(self):
        self.warnings = []
        self.changes_made = []

    def migrate_file(self, input_path: Path, output_path: Path = None) -> None:
        """Migrate a single Python file from async to sync patterns."""

        if output_path is None:
            # Create backup
            backup_path = input_path.with_suffix(input_path.suffix + '.backup')
            shutil.copy2(input_path, backup_path)
            output_path = input_path
            print(f"Created backup: {backup_path}")

        # Read input file
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Apply transformations
        original_content = content
        content = self._migrate_content(content)

        # Write output file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Report results
        if content != original_content:
            print(f"✓ Migrated: {input_path} -> {output_path}")
            print(f"  Changes made: {len(self.changes_made)}")
            for change in self.changes_made:
                print(f"    - {change}")
        else:
            print(f"  No changes needed for {input_path}")

        if self.warnings:
            print(f"  Warnings: {len(self.warnings)}")
            for warning in self.warnings:
                print(f"    ⚠️  {warning}")

    def _migrate_content(self, content: str) -> str:
        """Apply all migration transformations to content."""

        # Apply transformations in order
        transformations = [
            self._remove_asyncio_imports,
            self._convert_async_functions,
            self._convert_context_managers,
            self._remove_await_keywords,
            self._remove_asyncio_run_calls,
            self._update_pytest_decorators,
            self._update_exception_handlers,
        ]

        for transformation in transformations:
            content = transformation(content)

        return content

    def _remove_asyncio_imports(self, content: str) -> str:
        """Remove asyncio imports."""

        patterns = [
            (r'^import asyncio\n', ''),
            (r'^from asyncio import .*\n', ''),
            (r'import asyncio,\s*', ''),
            (r',\s*asyncio', ''),
        ]

        for pattern, replacement in patterns:
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
                self.changes_made.append("Removed asyncio import")

        return content

    def _convert_async_functions(self, content: str) -> str:
        """Convert async def to def."""

        pattern = r'^(\s*)async def\s+'

        def replace_func(match):
            indent = match.group(1)
            self.changes_made.append("Converted async def to def")
            return f"{indent}def "

        return re.sub(pattern, replace_func, content, flags=re.MULTILINE)

    def _convert_context_managers(self, content: str) -> str:
        """Convert async with statements."""

        # Pattern 1: async with await pytestlab.Bench.open()
        pattern1 = r'(\s*)async with await pytestlab\.Bench\.open\('

        def replace_bench(match):
            indent = match.group(1)
            self.changes_made.append("Converted async with await Bench.open() to with Bench.open()")
            return f"{indent}with pytestlab.Bench.open("

        content = re.sub(pattern1, replace_bench, content)

        # Pattern 2: async with MeasurementSession()
        pattern2 = r'(\s*)async with (MeasurementSession\([^)]*\))'

        def replace_session(match):
            indent = match.group(1)
            session_call = match.group(2)
            self.changes_made.append("Converted async with MeasurementSession() to with MeasurementSession()")
            return f"{indent}with {session_call}"

        content = re.sub(pattern2, replace_session, content)

        # General async with pattern
        pattern3 = r'(\s*)async with\s+'

        def replace_general(match):
            indent = match.group(1)
            self.warnings.append("Found generic 'async with' - please review manually")
            return f"{indent}with "

        content = re.sub(pattern3, replace_general, content)

        return content

    def _remove_await_keywords(self, content: str) -> str:
        """Remove await keywords from method calls."""

        # Common PyTestLab patterns
        patterns = [
            # await bench.instrument.method()
            (r'\bawait\s+(bench\.\w+\.\w+\([^)]*\))', r'\1'),
            # await instrument.method()
            (r'\bawait\s+((?:scope|dmm|psu|instr)\.\w+\([^)]*\))', r'\1'),
            # await meas.method()
            (r'\bawait\s+(meas\.\w+\([^)]*\))', r'\1'),
            # await variable.method()
            (r'\bawait\s+(\w+\.\w+\([^)]*\))', r'\1'),
        ]

        for pattern, replacement in patterns:
            matches = re.findall(pattern, content)
            if matches:
                content = re.sub(pattern, replacement, content)
                self.changes_made.append(f"Removed await from {len(matches)} method calls")

        # Check for remaining await keywords
        remaining_awaits = re.findall(r'\bawait\s+', content)
        if remaining_awaits:
            self.warnings.append(f"Found {len(remaining_awaits)} remaining 'await' keywords - review manually")

        return content

    def _remove_asyncio_run_calls(self, content: str) -> str:
        """Remove asyncio.run() calls and replace with direct function calls."""

        pattern = r'asyncio\.run\((\w+)\(\)\)'

        def replace_run(match):
            func_name = match.group(1)
            self.changes_made.append(f"Replaced asyncio.run({func_name}()) with {func_name}()")
            return f"{func_name}()"

        return re.sub(pattern, replace_run, content)

    def _update_pytest_decorators(self, content: str) -> str:
        """Remove pytest asyncio decorators."""

        pattern = r'^(\s*)@pytest\.mark\.asyncio\s*\n'

        matches = re.findall(pattern, content, re.MULTILINE)
        if matches:
            content = re.sub(pattern, '', content, flags=re.MULTILINE)
            self.changes_made.append(f"Removed {len(matches)} @pytest.mark.asyncio decorators")

        return content

    def _update_exception_handlers(self, content: str) -> str:
        """Update exception handling patterns that might be affected."""

        # Look for common async exception patterns that might need attention
        async_exception_patterns = [
            r'except\s+asyncio\.',
            r'TimeoutError',
            r'asyncio\.TimeoutError',
        ]

        for pattern in async_exception_patterns:
            if re.search(pattern, content):
                self.warnings.append(f"Found async exception pattern '{pattern}' - review exception handling")

        return content


def main():
    """Main entry point for the migration script."""

    parser = argparse.ArgumentParser(
        description="Migrate PyTestLab async code to synchronous patterns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python migrate_async_to_sync.py my_experiment.py
  python migrate_async_to_sync.py old_code.py new_code.py
  python migrate_async_to_sync.py experiments/*.py
        """
    )

    parser.add_argument(
        'input_files',
        nargs='+',
        help='Input Python files to migrate'
    )

    parser.add_argument(
        '-o', '--output',
        help='Output file (only valid for single input file)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )

    parser.add_argument(
        '--backup',
        action='store_true',
        default=True,
        help='Create backup files (default: True)'
    )

    args = parser.parse_args()

    # Validate arguments
    if len(args.input_files) > 1 and args.output:
        print("Error: Cannot specify output file with multiple input files")
        sys.exit(1)

    # Process files
    migrator = AsyncToSyncMigrator()
    total_files = 0
    total_changes = 0
    total_warnings = 0

    for input_file in args.input_files:
        input_path = Path(input_file)

        if not input_path.exists():
            print(f"Error: File not found: {input_path}")
            continue

        if not input_path.suffix == '.py':
            print(f"Warning: Skipping non-Python file: {input_path}")
            continue

        output_path = Path(args.output) if args.output else None

        if args.dry_run:
            print(f"[DRY RUN] Would migrate: {input_path}")
            # Read and analyze without writing
            with open(input_path, 'r', encoding='utf-8') as f:
                content = f.read()

            original_content = content
            migrator._migrate_content(content)

            if migrator.changes_made:
                print(f"  Would make {len(migrator.changes_made)} changes")
            if migrator.warnings:
                print(f"  Would generate {len(migrator.warnings)} warnings")
        else:
            try:
                migrator.migrate_file(input_path, output_path)
                total_files += 1
                total_changes += len(migrator.changes_made)
                total_warnings += len(migrator.warnings)
            except Exception as e:
                print(f"Error processing {input_path}: {e}")

        # Reset for next file
        migrator.changes_made = []
        migrator.warnings = []

    # Summary
    if not args.dry_run:
        print(f"\nMigration complete:")
        print(f"  Files processed: {total_files}")
        print(f"  Total changes: {total_changes}")
        print(f"  Total warnings: {total_warnings}")

        if total_warnings > 0:
            print("\n⚠️  Please review warnings and test thoroughly before committing changes!")

    print("\nRecommended next steps:")
    print("1. Review all warnings and manually fix remaining issues")
    print("2. Run your test suite to verify functionality")
    print("3. Test with actual hardware if applicable")
    print("4. Update any documentation or comments")


if __name__ == '__main__':
    main()
