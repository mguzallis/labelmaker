#!/bin/bash
# Double-click this file to run the Forza Label Generator.
# No Terminal typing needed -- this handles everything automatically.

# Move into the same folder this script lives in, no matter where it's
# double-clicked from or what the current directory happens to be.
cd "$(dirname "$0")"

echo "Forza Label Generator -- starting up..."
echo ""

# Create the virtual environment the first time this is ever run.
if [ ! -d "venv" ]; then
    echo "First time setup -- this will take a minute, just this once."
    python3 -m venv venv
fi

# Activate it.
source venv/bin/activate

# Install/confirm dependencies every run -- harmless and fast if already
# installed, and automatically picks up anything new after an update
# without needing a separate manual step.
pip install --quiet streamlit pymupdf pdfplumber Pillow

echo ""
echo "Launching the app in your browser..."
echo "(To stop the app later, close this window or press Ctrl+C.)"
echo ""

streamlit run app.py
