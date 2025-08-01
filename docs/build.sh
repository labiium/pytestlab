#!/bin/bash

# PyTestLab Documentation Build Script
# This script sets environment variables to suppress warnings and builds the documentation
#
# Usage:
#   ./build.sh          - Build documentation with clean output
#   ./build.sh --verbose - Build with verbose output for debugging

set -e  # Exit on any error

# Set Jupyter platform dirs to suppress deprecation warning
export JUPYTER_PLATFORM_DIRS=1

# Check if verbose flag is passed
VERBOSE=${1:-""}

echo "🔧 Building PyTestLab documentation..."
echo "   - Jupyter platform dirs: $JUPYTER_PLATFORM_DIRS"
echo "   - Build directory: $(pwd)/../site"
echo ""

# Build the documentation
if [[ "$VERBOSE" == "--verbose" ]]; then
    echo "   Running in verbose mode..."
    mkdocs build --verbose
else
    mkdocs build
fi

# Check build status
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Documentation build completed successfully!"
    echo "   View at: file://$(pwd)/../site/index.html"
else
    echo ""
    echo "❌ Documentation build failed!"
    exit 1
fi
