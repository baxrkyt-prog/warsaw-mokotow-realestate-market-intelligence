"""
analytics — pakiet warstwy analitycznej Ocean Plaza Market Intelligence.

Phase 0 (Listing Intelligence Layer):
  - listings        — KPI/agregaty ofert (office, residential, developers, buildings)
  - health          — Market Health Score (office, residential)
  - forecasting     — trend liniowy + projekcja
  - alerts          — reguły alertowe i log
  - watchlist       — obserwowane oferty
  - runs            — log scraperów (back-compat scrape_runs)
  - ocean_plaza     — KPI dla Ocean Plaza w competitive set

Phase 1+ doda:
  - transactions    — Transaction Intelligence Layer
  - pricing         — Pricing Intelligence Layer (Spread, Negotiation, Pressure)
  - confidence      — HIGH/MEDIUM/LOW + winsoryzacja

Ten __init__.py re-eksportuje publiczne API tak, by importy w app.py/pages/_ui.py
działały bez zmian (np. `from analytics import get_office_summary`).
"""

# Listings / agregaty ofert
from .listings import (
    get_office_summary,
    get_office_trend,
    get_office_vacancy_proxy,
    get_competitive_set,
    get_competitive_position,
    get_office_zone_summary,
    get_residential_summary,
    get_residential_trend,
    get_residential_zone_summary,
    get_developer_projects,
    get_project_snapshots,
    get_sales_velocity,
    get_invest_units_summary,
    get_building_history,
    get_building_units,
    get_developers_table,
    get_office_kpis_with_deltas,
    get_residential_kpis_with_deltas,
)

# Market Health
from .health import (
    compute_office_health_score,
    compute_residential_health_score,
    compute_project_health_score,
)

# Forecasting
from .forecasting import (
    forecast_trend,
    get_office_forecast,
    get_residential_forecast,
)

# Alerts
from .alerts import (
    get_alerts,
    mark_alerts_read,
    check_and_fire_alerts,
)

# Watchlist
from .watchlist import (
    get_watchlist_ids,
    set_watchlist,
    bulk_set_watchlist,
    get_watchlist_listings,
)

# Runs / log
from .runs import (
    get_scrape_log,
    get_last_scrape_ts,
)

# Ocean Plaza
from .ocean_plaza import (
    get_ocean_plaza_kpis,
)

# Transaction Intelligence Layer (Phase 1)
from .transactions import (
    get_transaction_kpis,
    get_transaction_trend,
    get_transaction_geography,
    get_recent_transactions,
)

# Pricing Intelligence Layer (Phase 4)
from .pricing import (
    materialize_pricing_spreads,
    get_pricing_kpis,
    get_spread_table,
    get_spread_history,
    compute_liquidity_score,
    compute_pricing_pressure_score,
)
from .confidence import confidence_level, winsorize

# Zone + Narrative (UX redesign)
from .zone import get_zone_intelligence
from .narrative import (
    get_market_deltas,
    get_what_changed,
    generate_market_narrative,
    generate_market_brief,
    generate_market_brief_pdf,
)

__all__ = [
    # listings
    "get_office_summary", "get_office_trend", "get_office_vacancy_proxy",
    "get_competitive_set", "get_competitive_position", "get_office_zone_summary",
    "get_residential_summary", "get_residential_trend", "get_residential_zone_summary",
    "get_developer_projects", "get_project_snapshots",
    "get_sales_velocity", "get_invest_units_summary",
    "get_building_history", "get_building_units", "get_developers_table",
    "get_office_kpis_with_deltas", "get_residential_kpis_with_deltas",
    # health
    "compute_office_health_score", "compute_residential_health_score",
    "compute_project_health_score",
    # forecasting
    "forecast_trend", "get_office_forecast", "get_residential_forecast",
    # alerts
    "get_alerts", "mark_alerts_read", "check_and_fire_alerts",
    # watchlist
    "get_watchlist_ids", "set_watchlist", "bulk_set_watchlist", "get_watchlist_listings",
    # runs
    "get_scrape_log", "get_last_scrape_ts",
    # ocean plaza
    "get_ocean_plaza_kpis",
    # transactions (Phase 1)
    "get_transaction_kpis", "get_transaction_trend",
    "get_transaction_geography", "get_recent_transactions",
    # pricing (Phase 4)
    "materialize_pricing_spreads", "get_pricing_kpis",
    "get_spread_table", "get_spread_history",
    "compute_liquidity_score", "compute_pricing_pressure_score",
    "confidence_level", "winsorize",
    # zone + narrative (UX)
    "get_zone_intelligence", "get_market_deltas", "get_what_changed",
    "generate_market_narrative", "generate_market_brief", "generate_market_brief_pdf",
]
