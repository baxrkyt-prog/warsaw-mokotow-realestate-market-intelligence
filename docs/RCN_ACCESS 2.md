# RCN — jak pozyskać dane transakcyjne dla Warszawy

## Stan prawny (2026)

Rejestr Cen Nieruchomości (RCN, dawniej RCiWN) prowadzi starosta — dla Warszawy:
**Biuro Geodezji i Katastru m.st. Warszawy (BGiK)**. Dane **nie są publiczne** —
wymaga się wniosku o udostępnienie materiałów zasobu (ustawa Prawo geodezyjne
i kartograficzne, art. 40a + rozporządzenie ws. opłat).

Co potwierdziliśmy w trakcie reconu (czerwiec 2026):
- **KIEG / Geoportal WFS** — udostępnia działki/budynki/obręby, **zero warstw cenowych**
  (zweryfikowane GetCapabilities — zobacz `python -m collectors run geoportal_wfs --discover`)
- **dane.gov.pl** — brak zbiorów RCN; są za to **ceny ofertowe deweloperów**
  (ustawa o jawności cen 2025) — potencjalny dodatkowy collector
- **NBP BaRN** — publiczny XLSX z cenami transakcyjnymi (zaimplementowane: `nbp_barn`),
  ale tylko poziom miasta, kwartalnie

## Ścieżka formalna (wniosek do BGiK)

1. Formularz **P** (wniosek główny) + załącznik **P5** (RCN)
   - online: https://geoportal.um.warszawa.pl (profil zaufany)
   - lub e-mail/osobiście: BGiK, ul. Sandomierska 12, Warszawa
2. We wniosku określić:
   - zakres przestrzenny: dzielnica Mokotów (lub obręby: Służewiec, Ksawerów…)
   - zakres czasowy: np. transakcje 2024–2026
   - rodzaj: lokale mieszkalne / użytkowe
   - format: **CSV lub XLSX** (zaznaczyć postać elektroniczną)
3. Opłata wg cennika (rozporządzenie): zbiór danych RCN to zwykle
   kilkadziesiąt–kilkaset PLN zależnie od liczby jednostek rejestrowych.
4. Czas realizacji: zwykle 1–4 tygodnie.

## Import wypisu do platformy

Po otrzymaniu pliku:

```bash
# auto-detekcja kolumn (typowe polskie nagłówki RCN)
python -m collectors run rcn --file wypis_rcn.csv --powiat warszawa

# typowe problemy:
python -m collectors run rcn --file wypis.csv --encoding cp1250   # kodowanie starostwa
python -m collectors run rcn --file wypis.xlsx --sheet "Arkusz1"  # XLSX
python -m collectors run rcn --file wypis.csv --mapping moj.json  # nietypowe nagłówki
```

Collector automatycznie:
- wykrywa kolumny (data, cena, powierzchnia, adres, obręb, izby, kondygnacja)
- odfiltrowuje lokale niemieszkalne (`--market-type` wymusza primary/secondary)
- **geokoduje adresy** przez GUGiK PRG (cache-first, fallback Nominatim)
- odrzuca outliers (sanity bounds 1000–100000 PLN/m² dla residential)
- loguje wszystko do `ingestion_runs`

## Alternatywy komercyjne (przyszłe collectory)

| Dostawca | Dane | Status |
|---|---|---|
| Cenatorium | pełen RCN + analizy | API płatne, brak collectora |
| SonarHome | wyceny + transakcje | brak publicznego API |
| AMRON (ZBP) | baza bankowa | dostęp członkowski |

Architektura collectors/ pozwala dodać każdy z nich jako nowy plik bez zmian
w analytics ani dashboardzie.

## Opóźnienie danych — UWAGA analityczna

RCN rejestruje akty notarialne z opóźnieniem **1–6 miesięcy**. Wszystkie
spread'y asking↔transaction liczą więc dzisiejsze ceny ofertowe vs. transakcje
sprzed kwartału. UI musi pokazywać datę najmłodszej transakcji (Faza 4/5).
