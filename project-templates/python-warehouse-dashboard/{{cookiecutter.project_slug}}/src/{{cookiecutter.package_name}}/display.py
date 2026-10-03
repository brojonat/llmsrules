"""Number formatting and meter math for templates. Charts are not drawn
here: they are d3 web components in static/components.js, fed data through
element attributes."""

from __future__ import annotations


def compact(v: float | None) -> str:
    """Three-ish significant digits, the way a stat tile wants."""
    if v is None:
        return "–"
    v = float(v)
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e4:
        return f"{v / 1e3:.1f}K"
    if a >= 100 or v == int(v):
        return f"{v:,.0f}"
    if a >= 1:
        return f"{v:.1f}"
    return f"{v:.2g}"


def meter(label: str, used: float, limit: float, fmt: str) -> dict:
    if limit <= 0:
        return {"label": label, "text": f"{compact(used)}, no limit", "pct": 0, "level": "ok"}
    pct = min(100, int(100 * used / limit))
    level = "critical" if pct >= 90 else "warning" if pct >= 75 else "ok"
    return {"label": label, "text": fmt.format(used, limit), "pct": pct, "level": level}
