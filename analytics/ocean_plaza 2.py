"""
analytics/ocean_plaza.py — KPI dla budynku Ocean Plaza w competitive set.
Phase 7 doda: pełna analiza stref 500/1000/2000m (Ocean Plaza Zone Intelligence).
"""

from .listings import get_competitive_set, get_office_summary


def get_ocean_plaza_kpis() -> dict:
    comp = get_competitive_set()
    all_office = get_office_summary()

    op = comp[comp["competitive_building"] == "Ocean Plaza"] if not comp.empty else None

    market_avg = all_office["price_per_m2"].mean() if not all_office.empty else None
    op_avg = op["price_per_m2"].mean() if op is not None and not op.empty else None
    premium = ((op_avg - market_avg) / market_avg * 100) if (op_avg and market_avg and market_avg > 0) else None

    has_area = op is not None and not op.empty and "area_m2" in op.columns and not op["area_m2"].isna().all()
    return {
        "op_active_offers": len(op) if op is not None else 0,
        "op_avg_price_m2":  round(op_avg, 2) if op_avg else None,
        "market_avg_price": round(market_avg, 2) if market_avg else None,
        "op_premium_pct":   round(premium, 1) if premium is not None else None,
        "op_avg_area":      round(float(op["area_m2"].mean()), 1) if has_area else None,
    }
