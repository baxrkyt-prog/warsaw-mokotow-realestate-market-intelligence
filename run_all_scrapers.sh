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
echo "[3/7] Inwestycje deweloperskie (scraper_developer.py)..."
"$VENV" "$DIR/scraper_developer.py" $SHOW_BROWSER 2>&1 | tee "$LOG_DIR/developer_$DATE.log"
echo "[3/7] Gotowe."

# 3b. Morizon — drugie źródło ofert mieszkaniowych
echo ""
echo "[3b/7] Morizon mieszkania (scraper_morizon.py)..."
"$VENV" "$DIR/scraper_morizon.py" $SHOW_BROWSER 2>&1 | tee "$LOG_DIR/morizon_$DATE.log" || \
    echo "[3b/7] WARN: Morizon nieudany — kontynuuję"
echo "[3b/7] Gotowe."

# 4. NBP BaRN — kwartalne ceny transakcyjne (darmowe; plik zmienia się raz na kwartał,
#    ale pobranie jest tanie i idempotentne)
echo ""
echo "[4/6] NBP BaRN (transaction benchmark)..."
(cd "$DIR" && "$VENV" -m collectors run nbp_barn) 2>&1 | tee "$LOG_DIR/nbp_$DATE.log" || \
    echo "[4/6] WARN: NBP niedostępne — kontynuuję (poprzednie dane w bazie zostają)"
echo "[4/6] Gotowe."

# 5. Geo backfill nowych ofert + materializacja spreadów
echo ""
echo "[5/6] Geo backfill + Pricing Intelligence (spready)..."
(cd "$DIR" && "$VENV" -m collectors run backfill_listings_geo --asset-class all --geocode-limit 30) \
    2>&1 | tee "$LOG_DIR/backfill_$DATE.log" || echo "[5/6] WARN: backfill częściowo nieudany"
(cd "$DIR" && "$VENV" -c "from analytics import materialize_pricing_spreads; print(materialize_pricing_spreads())") \
    2>&1 | tee "$LOG_DIR/spreads_$DATE.log"
(cd "$DIR" && "$VENV" -c "from analytics import record_lifecycle_snapshot; print(record_lifecycle_snapshot())") \
    2>&1 | tee "$LOG_DIR/lifecycle_$DATE.log"
# Weryfikacja delistingów pod URL — usuwa fałszywe (oferty żywe, zgubione przez scraper)
(cd "$DIR" && "$VENV" -m collectors run verify_delistings --asset-class all) \
    2>&1 | tee "$LOG_DIR/verify_delist_$DATE.log" || echo "WARN: weryfikacja delistingów nieudana"
echo "[5/6] Gotowe."

# 6. Alerty (w tym pricingowe)
echo ""
echo "[6/6] Alerty..."
(cd "$DIR" && "$VENV" -c "from analytics import check_and_fire_alerts; fired = check_and_fire_alerts(); print(f'{len(fired)} alertów')") \
    2>&1 | tee "$LOG_DIR/alerts_$DATE.log"
echo "[6/6] Gotowe."

echo ""
echo "========================================"
echo " Pipeline zakończony: $(date)"
echo " Logi: $LOG_DIR/"
echo "========================================"

# Usuń logi starsze niż 30 dni
find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
