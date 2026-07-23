# Exit on error
set -o errexit

pip install -r requirements.txt

# Create export dir
mkdir -p exports

# Optional: playwright browsers only if USE_PLAYWRIGHT=1
# playwright install chromium
