#!/bin/bash
# Quick installation script for ai-collab

set -e

echo "🚀 Installing AI Collaboration System..."

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
REQUIRED_VERSION="3.9"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ Error: Python 3.9 or higher is required"
    echo "   Current version: $PYTHON_VERSION"
    exit 1
fi

echo "✅ Python version: $PYTHON_VERSION"

# Install package
echo "📦 Installing ai-collab package..."
pip3 install -e .

# Initialize configuration
echo "⚙️  Initializing configuration..."
ai-collab init

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Configure providers: ai-collab config"
echo "  2. Check status: ai-collab status"
echo "  3. Run a task: ai-collab \"Build a tiny full-stack feature\""
echo ""
echo "Documentation:"
echo "  - Quick Start: QUICKSTART.md"
echo "  - Usage: docs/USAGE.md"
echo "  - README: README.md"
echo ""
