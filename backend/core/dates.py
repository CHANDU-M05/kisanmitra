"""
backend/core/dates.py — Agronomic calendar utilities.

Single source of truth for season derivation.
Import from here — do not inline this logic elsewhere.
"""
from datetime import date


def current_season(today: date | None = None) -> str:
    """Return the current agronomic season string for Karnataka.

    Kharif : June–October  (monsoon-sown)
    Rabi   : November–March (post-monsoon-sown)
    Zaid   : April–May      (short summer crop)

    Args:
        today: Override today's date (useful in tests). Defaults to date.today().

    Returns:
        Season string, e.g. "kharif_2026", "rabi_2026_2027", "zaid_2026".
    """
    if today is None:
        today = date.today()
    month = today.month
    year  = today.year
    if 6 <= month <= 10:
        return f"kharif_{year}"
    elif month >= 11:
        return f"rabi_{year}_{year + 1}"
    elif month <= 3:
        return f"rabi_{year - 1}_{year}"
    else:  # April–May
        return f"zaid_{year}"
