"""Public-data utilities with explicit commercial-friendly sources.

- NHTSA vPIC: public vehicle/WMI decode (https://vpic.nhtsa.dot.gov/api/)
- GLEIF LEI: CC0 LEI records (https://www.gleif.org/)
- BLS CPI: U.S. federal public data with attribution

All calls are bounded, session-free, and use no API keys.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

_NHTSA_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"
_GLEIF_BASE = "https://api.gleif.org/api/v1/lei-records"
_BLS_BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data"
_DEFAULT_TIMEOUT = 8.0

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.IGNORECASE)
_WMI_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{3}$", re.IGNORECASE)
_LEI_RE = re.compile(r"^[A-Z0-9]{20}$", re.IGNORECASE)

# Common BLS series shortcuts for inflation calculator.
_BLS_SERIES = {
    "cpi_u": "CUUR0000SA0",  # CPI-U All Urban Consumers, U.S. city average, all items
    "cpi_w": "CWUR0000SA0",  # CPI-W
    "cpi": "CUUR0000SA0",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_str(value: object) -> str:
    text = str(value or "").strip()
    if text in {"", "null", "None", "Not Applicable"}:
        return ""
    return text


async def _get_json(url: str, *, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"accept": "application/json", "user-agent": "delx-agent-utilities/0.1.5"})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return {"error": "invalid_json_shape", "url": url}
            return data
    except httpx.TimeoutException:
        return {"error": "upstream_timeout", "url": url, "timeout_seconds": timeout}
    except httpx.HTTPStatusError as exc:
        return {
            "error": "upstream_http_error",
            "url": url,
            "status_code": exc.response.status_code,
        }
    except Exception as exc:  # pragma: no cover - network edge
        return {"error": "upstream_failure", "url": url, "detail": str(exc)[:240]}


def _normalize_vin(raw: object) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()


async def _vin_decode(args: dict) -> dict:
    vin = _normalize_vin(args.get("vin") or args.get("VIN") or args.get("input"))
    if not vin:
        return {"error": "vin_required", "hint": "Pass a 17-character VIN."}
    if not _VIN_RE.match(vin):
        return {
            "error": "invalid_vin",
            "vin": vin,
            "hint": "VIN must be 17 characters, excluding I/O/Q.",
        }

    url = f"{_NHTSA_BASE}/DecodeVinValues/{quote(vin)}?format=json"
    payload = await _get_json(url)
    if payload.get("error"):
        return payload

    row = (payload.get("Results") or [{}])[0]
    if not isinstance(row, dict):
        return {"error": "empty_decode", "vin": vin}

    fields = {
        "make": _clean_str(row.get("Make")),
        "model": _clean_str(row.get("Model")),
        "model_year": _clean_str(row.get("ModelYear")),
        "body_class": _clean_str(row.get("BodyClass")),
        "vehicle_type": _clean_str(row.get("VehicleType")),
        "plant_country": _clean_str(row.get("PlantCountry")),
        "plant_city": _clean_str(row.get("PlantCity")),
        "manufacturer": _clean_str(row.get("Manufacturer") or row.get("ManufacturerName")),
        "trim": _clean_str(row.get("Trim")),
        "series": _clean_str(row.get("Series")),
        "drive_type": _clean_str(row.get("DriveType")),
        "fuel_type_primary": _clean_str(row.get("FuelTypePrimary")),
        "engine_cylinders": _clean_str(row.get("EngineCylinders")),
        "displacement_l": _clean_str(row.get("DisplacementL")),
        "doors": _clean_str(row.get("Doors")),
        "wmi": _clean_str(row.get("WMI") or vin[:3]),
    }
    error_code = _clean_str(row.get("ErrorCode"))
    error_text = _clean_str(row.get("ErrorText"))
    warnings = []
    if error_code and error_code not in {"0", "0,0"}:
        warnings.append(error_text or f"NHTSA error code {error_code}")

    return {
        "schema": "delx/vin-decode/v1",
        "vin": vin,
        "decoded": fields,
        "error_code": error_code or "0",
        "error_text": error_text or "0 - VIN decoded clean",
        "warnings": warnings,
        "source": {
            "provider": "NHTSA vPIC",
            "url": url,
            "attribution": "Vehicle data from the U.S. NHTSA Product Information Catalog Vehicle Listing (vPIC).",
            "retrieved_at": _now_iso(),
        },
    }


async def _wmi_decode(args: dict) -> dict:
    wmi = _normalize_vin(args.get("wmi") or args.get("WMI") or args.get("input"))
    if len(wmi) > 3:
        wmi = wmi[:3]
    if not wmi:
        return {"error": "wmi_required", "hint": "Pass a 3-character WMI (often the first 3 VIN chars)."}
    if not _WMI_RE.match(wmi):
        return {"error": "invalid_wmi", "wmi": wmi, "hint": "WMI must be 3 VIN-safe characters."}

    url = f"{_NHTSA_BASE}/DecodeWMI/{quote(wmi)}?format=json"
    payload = await _get_json(url)
    if payload.get("error"):
        return payload

    row = (payload.get("Results") or [{}])[0]
    if not isinstance(row, dict):
        return {"error": "empty_decode", "wmi": wmi}

    return {
        "schema": "delx/wmi-decode/v1",
        "wmi": wmi,
        "make": _clean_str(row.get("Make") or row.get("CommonName")),
        "manufacturer_name": _clean_str(row.get("ManufacturerName")),
        "parent_company_name": _clean_str(row.get("ParentCompanyName")),
        "vehicle_type": _clean_str(row.get("VehicleType")),
        "common_name": _clean_str(row.get("CommonName")),
        "date_available_to_public": _clean_str(row.get("DateAvailableToPublic")),
        "url": _clean_str(row.get("URL")) or None,
        "source": {
            "provider": "NHTSA vPIC",
            "url": url,
            "attribution": "WMI data from the U.S. NHTSA Product Information Catalog Vehicle Listing (vPIC).",
            "retrieved_at": _now_iso(),
        },
    }


async def _lei_lookup(args: dict) -> dict:
    lei = re.sub(r"[^A-Za-z0-9]", "", str(args.get("lei") or args.get("LEI") or args.get("input") or "")).upper()
    if not lei:
        return {"error": "lei_required", "hint": "Pass a 20-character Legal Entity Identifier."}
    if not _LEI_RE.match(lei):
        return {"error": "invalid_lei", "lei": lei, "hint": "LEI must be exactly 20 alphanumeric characters."}

    # GLEIF filter syntax uses brackets; httpx params handle encoding.
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                _GLEIF_BASE,
                params={"filter[lei]": lei, "page[size]": 1},
                headers={"accept": "application/vnd.api+json", "user-agent": "delx-agent-utilities/0.1.5"},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        return {"error": "upstream_timeout", "timeout_seconds": _DEFAULT_TIMEOUT}
    except httpx.HTTPStatusError as exc:
        return {"error": "upstream_http_error", "status_code": exc.response.status_code}
    except Exception as exc:  # pragma: no cover
        return {"error": "upstream_failure", "detail": str(exc)[:240]}

    if not isinstance(payload, dict):
        return {"error": "invalid_json_shape"}
    data = payload.get("data") or []
    if not data:
        return {
            "schema": "delx/lei-lookup/v1",
            "lei": lei,
            "found": False,
            "entity": None,
            "registration": None,
            "source": {
                "provider": "GLEIF",
                "attribution": "LEI data under GLEIF terms (CC0 for LEI data); not legal advice.",
                "retrieved_at": _now_iso(),
            },
        }

    record = data[0] if isinstance(data[0], dict) else {}
    attrs = record.get("attributes") or {}
    entity = attrs.get("entity") or {}
    registration = attrs.get("registration") or {}
    legal_name = entity.get("legalName") or {}
    if isinstance(legal_name, dict):
        legal_name_text = _clean_str(legal_name.get("name"))
    else:
        legal_name_text = _clean_str(legal_name)

    address = entity.get("legalAddress") or {}
    country = ""
    if isinstance(address, dict):
        country = _clean_str(address.get("country"))

    return {
        "schema": "delx/lei-lookup/v1",
        "lei": lei,
        "found": True,
        "entity": {
            "legal_name": legal_name_text,
            "status": _clean_str(entity.get("status")),
            "jurisdiction": _clean_str(entity.get("jurisdiction")),
            "legal_form": _clean_str((entity.get("legalForm") or {}).get("id") if isinstance(entity.get("legalForm"), dict) else entity.get("legalForm")),
            "country": country,
            "category": _clean_str(entity.get("category")),
        },
        "registration": {
            "status": _clean_str(registration.get("status")),
            "initial_registration_date": _clean_str(registration.get("initialRegistrationDate")),
            "last_update_date": _clean_str(registration.get("lastUpdateDate")),
            "next_renewal_date": _clean_str(registration.get("nextRenewalDate")),
            "managing_lou": _clean_str(registration.get("managingLou")),
            "corroboration_level": _clean_str(registration.get("corroborationLevel")),
        },
        "source": {
            "provider": "GLEIF",
            "attribution": "LEI data under GLEIF terms (CC0 for LEI data); not legal advice or KYC.",
            "retrieved_at": _now_iso(),
        },
    }


def _parse_year(raw: object, *, default: int | None = None) -> int | None:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return None
    if year < 1913 or year > 2100:
        return None
    return year


async def _inflation_calculator(args: dict) -> dict:
    """Revalue an amount between two years using BLS CPI-U (or CPI-W)."""
    try:
        amount = float(args.get("amount") if args.get("amount") is not None else args.get("value"))
    except (TypeError, ValueError):
        return {"error": "amount_required", "hint": "Pass a numeric amount to revalue."}

    from_year = _parse_year(args.get("from_year") or args.get("start_year"))
    to_year = _parse_year(args.get("to_year") or args.get("end_year") or args.get("year"))
    if from_year is None or to_year is None:
        return {
            "error": "from_year_and_to_year_required",
            "hint": "ISO calendar years, e.g. from_year=2015 to_year=2024.",
        }
    if from_year > to_year:
        from_year, to_year = to_year, from_year
        amount_note = "years_swapped"
    else:
        amount_note = None

    series_key = str(args.get("series") or "cpi_u").strip().lower()
    series_id = _BLS_SERIES.get(series_key, series_key.upper())
    # BLS public API allows a limited year window per call.
    if to_year - from_year > 20:
        return {"error": "range_too_large", "max_span_years": 20, "got": to_year - from_year}

    url = f"{_BLS_BASE}/{quote(series_id)}"
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                url,
                params={"startyear": str(from_year), "endyear": str(to_year)},
                headers={"accept": "application/json", "user-agent": "delx-agent-utilities/0.1.5"},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        return {"error": "upstream_timeout", "timeout_seconds": _DEFAULT_TIMEOUT}
    except httpx.HTTPStatusError as exc:
        return {"error": "upstream_http_error", "status_code": exc.response.status_code}
    except Exception as exc:  # pragma: no cover
        return {"error": "upstream_failure", "detail": str(exc)[:240]}

    if not isinstance(payload, dict) or payload.get("status") not in {None, "REQUEST_SUCCEEDED"}:
        if isinstance(payload, dict) and payload.get("status") and payload.get("status") != "REQUEST_SUCCEEDED":
            return {
                "error": "bls_request_failed",
                "status": payload.get("status"),
                "message": payload.get("message") or payload.get("messageText"),
            }

    series_list = ((payload.get("Results") or {}).get("series") or []) if isinstance(payload, dict) else []
    if not series_list:
        return {"error": "series_empty", "series_id": series_id}

    points = series_list[0].get("data") or []
    # Prefer annual averages if present (M13), else average monthly values per year.
    by_year: dict[int, list[float]] = {}
    annual: dict[int, float] = {}
    for point in points:
        if not isinstance(point, dict):
            continue
        try:
            year = int(point.get("year"))
            value = float(point.get("value"))
        except (TypeError, ValueError):
            continue
        period = str(point.get("period") or "")
        if period == "M13":
            annual[year] = value
        elif period.startswith("M"):
            by_year.setdefault(year, []).append(value)

    def index_for(year: int) -> float | None:
        if year in annual:
            return annual[year]
        months = by_year.get(year) or []
        if not months:
            return None
        return sum(months) / len(months)

    start_index = index_for(from_year)
    end_index = index_for(to_year)
    if start_index is None or end_index is None or start_index == 0:
        return {
            "error": "index_unavailable",
            "series_id": series_id,
            "from_year": from_year,
            "to_year": to_year,
            "hint": "BLS may not publish a complete annual average for one of the years yet.",
        }

    revalued = amount * (end_index / start_index)
    result: dict[str, Any] = {
        "schema": "delx/inflation-calculator/v1",
        "amount": amount,
        "from_year": from_year,
        "to_year": to_year,
        "series_id": series_id,
        "series_label": series_key,
        "start_index": start_index,
        "end_index": end_index,
        "revalued_amount": revalued,
        "factor": end_index / start_index,
        "methodology": "amount * (CPI_end / CPI_start) using BLS annual average when available, otherwise mean of published months.",
        "disclaimer": "Informational only — not investment, tax, or legal advice. BLS data may be revised.",
        "source": {
            "provider": "U.S. Bureau of Labor Statistics",
            "series_id": series_id,
            "attribution": "U.S. BLS public data; cite BLS and retrieval date for redistribution.",
            "retrieved_at": _now_iso(),
            "url": url,
        },
    }
    if amount_note:
        result["note"] = amount_note
    return result
