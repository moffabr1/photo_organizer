#!/bin/bash
# Photo Organizer — one-time setup
set -e

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Setup complete."
echo ""
echo "To run:"
echo "  source venv/bin/activate"
echo "  python main.py"
