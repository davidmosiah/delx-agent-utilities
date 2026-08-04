"""First-party timezone, unit conversion, and business-day utilities.

No network, no API keys, no datasets with redistribution risk beyond
stdlib zoneinfo and hard-coded public-domain conversion factors / US
weekend rules.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# ─── Units ────────────────────────────────────────────────────────────

# All linear factors convert TO a canonical SI-ish base, then to target.
_LENGTH_TO_M = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "km": 1000.0,
    "kilometer": 1000.0,
    "kilometers": 1000.0,
    "cm": 0.01,
    "mm": 0.001,
    "mi": 1609.344,
    "mile": 1609.344,
    "miles": 1609.344,
    "yd": 0.9144,
    "yard": 0.9144,
    "yards": 0.9144,
    "ft": 0.3048,
    "foot": 0.3048,
    "feet": 0.3048,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
    "nmi": 1852.0,
    "nm": 1852.0,
}

_MASS_TO_KG = {
    "kg": 1.0,
    "kilogram": 1.0,
    "kilograms": 1.0,
    "g": 0.001,
    "gram": 0.001,
    "grams": 0.001,
    "mg": 1e-6,
    "lb": 0.45359237,
    "lbs": 0.45359237,
    "pound": 0.45359237,
    "pounds": 0.45359237,
    "oz": 0.028349523125,
    "ounce": 0.028349523125,
    "ounces": 0.028349523125,
    "t": 1000.0,
    "tonne": 1000.0,
    "metric_ton": 1000.0,
}

_VOLUME_TO_L = {
    "l": 1.0,
    "liter": 1.0,
    "liters": 1.0,
    "litre": 1.0,
    "litres": 1.0,
    "ml": 0.001,
    "m3": 1000.0,
    "gal": 3.785411784,
    "gallon": 3.785411784,
    "gallons": 3.785411784,
    "qt": 0.946352946,
    "pt": 0.473176473,
    "cup": 0.2365882365,
    "floz": 0.0295735295625,
}

_TIME_TO_S = {
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "ms": 0.001,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
    "week": 604800.0,
    "weeks": 604800.0,
}

_DATA_TO_B = {
    "b": 1.0,
    "byte": 1.0,
    "bytes": 1.0,
    "kb": 1000.0,
    "mb": 1_000_000.0,
    "gb": 1_000_000_000.0,
    "tb": 1_000_000_000_000.0,
    "kib": 1024.0,
    "mib": 1024.0**2,
    "gib": 1024.0**3,
    "tib": 1024.0**4,
}

_DIMENSIONS: dict[str, dict[str, float]] = {
    "length": _LENGTH_TO_M,
    "mass": _MASS_TO_KG,
    "volume": _VOLUME_TO_L,
    "time": _TIME_TO_S,
    "data": _DATA_TO_B,
}

_TEMP_UNITS = {"c", "celsius", "f", "fahrenheit", "k", "kelvin"}


def _norm_unit(raw: object) -> str:
    return str(raw or "").strip().lower().replace(" ", "_")


def _convert_temperature(value: float, from_u: str, to_u: str) -> float:
    # to celsius
    if from_u in {"c", "celsius"}:
        c = value
    elif from_u in {"f", "fahrenheit"}:
        c = (value - 32.0) * 5.0 / 9.0
    elif from_u in {"k", "kelvin"}:
        c = value - 273.15
    else:
        raise ValueError(f"unsupported temperature unit: {from_u}")

    if to_u in {"c", "celsius"}:
        return c
    if to_u in {"f", "fahrenheit"}:
        return c * 9.0 / 5.0 + 32.0
    if to_u in {"k", "kelvin"}:
        return c + 273.15
    raise ValueError(f"unsupported temperature unit: {to_u}")


def _unit_convert(args: dict) -> dict:
    """Convert one value or a batch of conversions (max 100)."""
    conversions = args.get("conversions")
    if conversions is None:
        conversions = [
            {
                "value": args.get("value"),
                "from_unit": args.get("from_unit") or args.get("from"),
                "to_unit": args.get("to_unit") or args.get("to"),
            }
        ]
    if not isinstance(conversions, list) or not conversions:
        return {"error": "conversions_required", "hint": "Pass value+from_unit+to_unit or conversions[]."}
    if len(conversions) > 100:
        return {"error": "too_many_conversions", "max": 100, "got": len(conversions)}

    results: list[dict[str, Any]] = []
    for idx, item in enumerate(conversions):
        if not isinstance(item, dict):
            results.append({"index": idx, "ok": False, "error": "invalid_item"})
            continue
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            results.append({"index": idx, "ok": False, "error": "value_must_be_number"})
            continue
        from_u = _norm_unit(item.get("from_unit") or item.get("from"))
        to_u = _norm_unit(item.get("to_unit") or item.get("to"))
        if not from_u or not to_u:
            results.append({"index": idx, "ok": False, "error": "from_unit_and_to_unit_required"})
            continue

        try:
            if from_u in _TEMP_UNITS or to_u in _TEMP_UNITS:
                if from_u not in _TEMP_UNITS or to_u not in _TEMP_UNITS:
                    raise ValueError("temperature units cannot mix with other dimensions")
                out = _convert_temperature(value, from_u, to_u)
                dimension = "temperature"
            else:
                dimension = None
                table = None
                for name, factors in _DIMENSIONS.items():
                    if from_u in factors and to_u in factors:
                        dimension = name
                        table = factors
                        break
                if table is None or dimension is None:
                    raise ValueError(f"unsupported unit pair: {from_u} → {to_u}")
                base = value * table[from_u]
                out = base / table[to_u]
        except ValueError as exc:
            results.append({"index": idx, "ok": False, "error": str(exc), "from_unit": from_u, "to_unit": to_u})
            continue

        results.append(
            {
                "index": idx,
                "ok": True,
                "value": value,
                "from_unit": from_u,
                "to_unit": to_u,
                "result": out,
                "dimension": dimension,
            }
        )

    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "schema": "delx/unit-convert/v1",
        "count": len(results),
        "ok_count": ok_count,
        "conversions": results,
    }


# ─── Timezone ─────────────────────────────────────────────────────────


def _parse_instant(raw: object) -> datetime:
    if raw is None or str(raw).strip() == "" or str(raw).strip().lower() == "now":
        return datetime.now(timezone.utc)
    text = str(raw).strip()
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    try:
        # float unix
        as_float = float(text)
        if abs(as_float) > 1e11:  # ms
            as_float /= 1000.0
        return datetime.fromtimestamp(as_float, tz=timezone.utc)
    except ValueError:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _timezone_lookup(args: dict) -> dict:
    tz_name = str(args.get("timezone") or args.get("tz") or "").strip()
    if not tz_name:
        return {
            "error": "timezone_required",
            "hint": "IANA timezone id, e.g. America/Sao_Paulo or UTC.",
        }
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return {
            "error": "unknown_timezone",
            "timezone": tz_name,
            "hint": "Use a valid IANA timezone id from the host tzdata.",
        }
    except Exception as exc:  # pragma: no cover - platform zoneinfo edge
        return {"error": "timezone_unavailable", "timezone": tz_name, "detail": str(exc)}

    instant = _parse_instant(args.get("at") or args.get("timestamp") or "now")
    local = instant.astimezone(zone)
    offset = local.utcoffset() or timedelta(0)
    offset_seconds = int(offset.total_seconds())
    hours, rem = divmod(abs(offset_seconds), 3600)
    minutes = rem // 60
    sign = "+" if offset_seconds >= 0 else "-"
    offset_str = f"{sign}{hours:02d}:{minutes:02d}"
    dst = bool(local.dst() and local.dst().total_seconds() != 0)

    return {
        "schema": "delx/timezone-lookup/v1",
        "timezone": tz_name,
        "at_utc": instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "local_time": local.isoformat(),
        "offset": offset_str,
        "offset_seconds": offset_seconds,
        "abbreviation": local.tzname(),
        "is_dst": dst,
        "source": "IANA tzdata via Python zoneinfo",
    }


# ─── Business days ────────────────────────────────────────────────────

# Fixed-date US federal holidays (month, day). Observed-date rules are
# applied for weekend collisions. Floating holidays (MLK, Presidents, etc.)
# use simple Nth-weekday rules.
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """weekday: Mon=0 … Sun=6. n: 1=first, -1=last."""
    if n > 0:
        d = date(year, month, 1)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        d += timedelta(weeks=n - 1)
        return d
    # last
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed(d: date) -> date:
    if d.weekday() == 5:  # Saturday → Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday → Monday
        return d + timedelta(days=1)
    return d


def _us_federal_holidays(year: int) -> set[date]:
    fixed = [
        date(year, 1, 1),  # New Year
        date(year, 6, 19),  # Juneteenth
        date(year, 7, 4),  # Independence
        date(year, 11, 11),  # Veterans
        date(year, 12, 25),  # Christmas
    ]
    floating = [
        _nth_weekday(year, 1, 0, 3),  # MLK — 3rd Monday Jan
        _nth_weekday(year, 2, 0, 3),  # Presidents — 3rd Monday Feb
        _nth_weekday(year, 5, 0, -1),  # Memorial — last Monday May
        _nth_weekday(year, 9, 0, 1),  # Labor — 1st Monday Sep
        _nth_weekday(year, 10, 0, 2),  # Columbus — 2nd Monday Oct
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving — 4th Thursday Nov
    ]
    return {_observed(d) for d in fixed + floating}


def _parse_date(raw: object) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _business_days(args: dict) -> dict:
    start = _parse_date(args.get("start_date") or args.get("start"))
    end = _parse_date(args.get("end_date") or args.get("end"))
    if start is None or end is None:
        return {
            "error": "start_date_and_end_date_required",
            "hint": "ISO dates YYYY-MM-DD. Inclusive range.",
        }
    if end < start:
        return {"error": "end_before_start", "start_date": start.isoformat(), "end_date": end.isoformat()}

    calendar = str(args.get("calendar") or "weekdays").strip().lower()
    if calendar not in {"weekdays", "us_federal"}:
        return {
            "error": "unsupported_calendar",
            "calendar": calendar,
            "hint": "weekdays (Mon–Fri) or us_federal (excludes US federal holidays).",
        }

    span_days = (end - start).days + 1
    if span_days > 3660:  # ~10 years
        return {"error": "range_too_large", "max_days": 3660, "got_days": span_days}

    holidays: set[date] = set()
    if calendar == "us_federal":
        years = range(start.year, end.year + 1)
        for y in years:
            holidays |= _us_federal_holidays(y)

    business: list[str] = []
    excluded_weekends = 0
    excluded_holidays = 0
    cursor = start
    while cursor <= end:
        if cursor.weekday() >= 5:
            excluded_weekends += 1
        elif cursor in holidays:
            excluded_holidays += 1
        else:
            business.append(cursor.isoformat())
        cursor += timedelta(days=1)

    return {
        "schema": "delx/business-days/v1",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "calendar": calendar,
        "business_day_count": len(business),
        "calendar_day_count": span_days,
        "excluded_weekends": excluded_weekends,
        "excluded_holidays": excluded_holidays,
        "business_days": business if len(business) <= 366 else business[:366],
        "truncated": len(business) > 366,
        "note": "Inclusive range. us_federal uses observed US federal holiday rules; not legal advice.",
    }
