#!/bin/bash
# run_all_scrapers.sh — uruchamia wszystkie trzy scrapery sekwencyjnie
# Użycie: ./run_all_scrapers.sh
#         ./run_all_scrapers.sh --show-browser   (z widoczną przeglądarką)

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/venv/bin/python"
LOG_DIR="$DIR/logs"
DATE=$(date +%Y-%m-%d_%H-%M-%S)

mkdir -p "$LOG_DIR"

SHOW_BROWSER=""
if [[ "$1" == "--show-browser" ]]; then
    SHOW_BROWSER="--show-browser"
fi

echo "========================================"
echo " Ocean Plaza MI — scrape wszystkich źródeł"
echo " Start: $(date)"
echo "========================================"

# 1. Biura
echo ""
echo "[1/3] Biura (scraper_office.py)..."
"$VENV" "$DIR/scraper_office.py" $SHOW_BROWSER 2>&1 | tee "$LOG_DIR/office_$DATE.log"
echo "[1/3] Gotowe."

# 2. Mieszkania — sprzedaż
echo ""
echo "[2/3] Mieszkania sprzedaż (scraper_residential.py)..."
"$VENV" "$DIR/scraper_residential.py" $SHOW_BROWSER 2>&1 | tee "$LOG_DIR/residential_$DATE.log"
echo "[2/3] Gotowe."

# 3. Deweloperzy
echo ""
echo "[3/3] Inwestycje deweloperskie (scraper_developer.py)..."
"$VENV" "$DIR/scraper_developer.py" $SHOW_BROWSER 2>&1 | tee "$LOG_DIR/developer_$DATE.log"
echo "[3/3] Gotowe."

echo ""
echo "========================================"
echo " Scrape zakończony: $(date)"
echo " Logi: $LOG_DIR/"
echo "========================================"

# Usuń logi starsze niż 30 dni
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
