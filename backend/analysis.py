"""Deterministic descriptive statistics and review-only quality/anomaly findings.

Missing means an actual null, not an empty string or a textual null token. Date
inference refuses ambiguous day/month order. Heuristics never change source data.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import date, datetime
from itertools import combinations

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_integer_dtype, is_numeric_dtype
from rapidfuzz.fuzz import ratio
from scipy import stats

from .ingestion import numeric_candidate

_ROW_LIMIT = 200
_SENTINELS = {"na", "n/a", "null", "none", "nil", "nan", "unknown", "missing", "?", "-", "-999", "-9999", "9999"}
_DATE_NAME = re.compile(r"date|timestamp|birthday|dob|_at$", re.I)
_NUMERIC_NAME = re.compile(r"(?:^|_)(?:amount|price|salary|age|quantity|count|cost|score|weight|height|total)(?:$|_)", re.I)
_ID_NAME = re.compile(r"(?:^|[\s_])(?:id|identifier|zip|postcode|postal|phone|code)(?:$|[\s_])", re.I)
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?\Z")
_SLASH = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\Z")


def json_safe(value):
    """Return strict JSON scalars/containers without changing source objects."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray, pd.Index)):
        return [json_safe(item) for item in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return float(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.datetime64, pd.Timedelta)):
        return str(value)
    if isinstance(value, str):
        return value
    return str(value)


def _number_values(series: pd.Series) -> np.ndarray:
    if not is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype):
        return np.array([], dtype=float)
    return series.to_numpy(dtype=float, na_value=np.nan)


def _finite(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _numeric_profile(series: pd.Series) -> dict:
    raw = _number_values(series)
    values = raw[np.isfinite(raw)]
    result = {key: None for key in ("min", "max", "mean", "median", "std", "variance", "q1", "q3", "iqr", "skewness", "kurtosis")}
    result.update(zero_count=int(np.sum(values == 0)), negative_count=int(np.sum(values < 0)),
                  infinity_count=int(np.isinf(raw).sum()), finite_count=int(len(values)),
                  percentiles={}, histogram={"counts": [], "edges": []})
    if not len(values):
        return result
    scale = float(np.max(np.abs(values))) or 1.0
    scaled = values / scale
    with np.errstate(all="ignore"):
        quantiles = np.quantile(scaled, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
        q1, median, q3 = quantiles[2:5]
        deviation = np.std(scaled, ddof=1) * scale if len(values) > 1 else np.nan
        finite_series = series.iloc[np.flatnonzero(np.isfinite(raw))]
        result.update(min=json_safe(finite_series.min()), max=json_safe(finite_series.max()), mean=_finite(np.mean(scaled) * scale),
                      median=_finite(median * scale), std=_finite(deviation), variance=_finite(deviation * deviation),
                      q1=_finite(q1 * scale), q3=_finite(q3 * scale), iqr=_finite((q3 - q1) * scale))
        center = np.mean(scaled)
        reliable_moments = np.max(np.abs(scaled - center)) >= 10 * np.finfo(float).eps * max(abs(center), np.finfo(float).tiny)
        if len(values) >= 3 and reliable_moments:
            result["skewness"] = _finite(stats.skew(scaled, bias=False))
        if len(values) >= 4 and reliable_moments:
            result["kurtosis"] = _finite(stats.kurtosis(scaled, bias=False))
        result["percentiles"] = {str(p): _finite(v * scale) for p, v in zip([1, 5, 25, 50, 75, 95, 99], quantiles)}
        if values.min() == values.max():
            result["histogram"] = {"counts": [len(values)], "edges": [float(values[0]), float(values[0])]}
        else:
            counts, edges = np.histogram(scaled, bins=min(20, max(2, math.ceil(math.sqrt(len(values))))))
            result["histogram"] = {"counts": counts.tolist(), "edges": (edges * scale).tolist()}
    return result


def _date_value(value: object) -> tuple[pd.Timestamp | None, str | None, bool]:
    if isinstance(value, (datetime, date, pd.Timestamp)) and not pd.isna(value):
        return pd.Timestamp(value), "datetime", False
    if not isinstance(value, str):
        return None, None, False
    style = None
    try:
        if _ISO.fullmatch(value):
            style = "ISO-8601"
            return pd.Timestamp(datetime.fromisoformat(value.replace("Z", "+00:00"))), style, False
        match = _SLASH.fullmatch(value)
        if match:
            a, b, _ = map(int, match.groups())
            if 1 <= a <= 12 and 1 <= b <= 12 and a != b:
                return None, "ambiguous slash date", True
            style = "%d/%m/%Y" if a > 12 else "%m/%d/%Y"
            return pd.Timestamp(datetime.strptime(value, style)), style, False
    except (ValueError, OverflowError):
        return None, style or "date-like", False
    return None, None, False


def _date_details(series: pd.Series, name: str) -> tuple[dict | None, list, list, list]:
    parsed = [_date_value(value) for value in series]
    styles = Counter(style for _, style, _ in parsed if style)
    if not styles and not _DATE_NAME.search(name) and not is_datetime64_any_dtype(series.dtype):
        return None, [], [], []
    valid = [(idx, value) for idx, (value, _, _) in zip(series.index, parsed) if value is not None]
    invalid = [idx for idx, original, (value, _, ambiguous) in zip(series.index, series, parsed)
               if not pd.isna(original) and value is None and not ambiguous]
    ambiguous = [idx for idx, (_, _, uncertain) in zip(series.index, parsed) if uncertain]
    # UTC is used for summary comparisons only, not to transform source cells.
    normalized = [value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC") for _, value in valid]
    low, high = (min(normalized), max(normalized)) if normalized else (None, None)
    return {"min": json_safe(low), "max": json_safe(high), "valid_count": len(valid),
            "invalid_count": len(invalid), "ambiguous_count": len(ambiguous),
            "range_days": (high.to_pydatetime() - low.to_pydatetime()).total_seconds() / 86400 if low is not None else None,
            "formats": dict(styles), "possible_format_inconsistencies": len(styles) > 1}, valid, invalid, ambiguous


def _common(series: pd.Series, limit: int = 10) -> list[dict]:
    # Report observed values in record order, not unused categorical dictionary entries.
    observed = series.astype(object) if isinstance(series.dtype, pd.CategoricalDtype) else series
    counts = observed.value_counts(dropna=True, sort=False)
    indexed = list(enumerate(counts.items()))
    indexed.sort(key=lambda pair: (-pair[1][1], pair[0]))
    return [{"value": json_safe(value), "count": int(count)} for _, (value, count) in indexed[:limit]]


def _categorical_profile(series: pd.Series) -> dict:
    text = [value for value in series.dropna() if isinstance(value, str)]
    counts = Counter(text)
    ordered = sorted(counts, key=lambda value: (-counts[value], value))
    lengths = [len(value) for value in text]
    case_groups, whitespace_groups = {}, {}
    for value in ordered:
        case_groups.setdefault(value.casefold(), []).append(value)
        whitespace_groups.setdefault(value.strip(), []).append(value)
    rare_limit = max(1, int(len(text) * 0.01))
    return {"unique_categories": int(series.nunique()), "frequencies": _common(series, 50),
            "rare_categories": [{"value": v, "count": counts[v]} for v in ordered if counts[v] <= rare_limit][:50],
            "whitespace_variants": [group for group in whitespace_groups.values() if len(group) > 1][:20],
            "case_differences": [group for group in case_groups.values() if len(group) > 1][:20],
            "string_lengths": {"min": min(lengths) if lengths else None, "max": max(lengths) if lengths else None,
                               "mean": sum(lengths) / len(lengths) if lengths else None},
            "frequencies_truncated": series.nunique() > 50}


def profile(df: pd.DataFrame) -> dict:
    rows, columns = df.shape
    missing = int(df.isna().sum().sum())
    profiles = []
    distribution = Counter()
    empty, constant = [], []
    numeric_columns = []
    for name in df.columns:
        series = df[name]
        present, distinct = int(series.notna().sum()), int(series.nunique(dropna=True))
        dates, _, _, ambiguous = _date_details(series, str(name))
        numeric = None
        if is_bool_dtype(series.dtype):
            semantic = "boolean"
        elif is_numeric_dtype(series.dtype):
            semantic, numeric = "numeric", _numeric_profile(series)
            numeric_columns.append(name)
        elif is_datetime64_any_dtype(series.dtype):
            semantic = "date"
        elif dates and dates["valid_count"] == present and present and not ambiguous:
            semantic = "date"
        elif present and all(numeric_candidate(value) is not None for value in series.dropna()):
            semantic = "numeric_string"
        else:
            semantic = "categorical" if distinct <= max(20, rows * 0.2) else "text"
        distribution[semantic] += 1
        if not present:
            empty.append(name)
        if distinct == 1:
            constant.append(name)
        profiles.append({"name": str(name), "storage_type": str(series.dtype), "semantic_type": semantic,
                         "non_null_count": present, "missing_count": rows - present,
                         "missing_percentage": 100 * (rows - present) / rows if rows else 0.0,
                         "distinct_count": distinct, "distinct_percentage": 100 * distinct / present if present else 0.0,
                         "samples": [json_safe(value) for value in series.dropna().head(5)], "common_values": _common(series),
                         "numeric": numeric, "categorical": _categorical_profile(series) if semantic in {"categorical", "text", "numeric_string", "boolean"} else None,
                         "dates": dates})
    correlation_columns = numeric_columns[:50]
    normalized = {}
    for name in correlation_columns:
        values = _number_values(df[name]).copy()
        values[~np.isfinite(values)] = np.nan
        finite = values[np.isfinite(values)]
        normalized[name] = values / (float(np.max(np.abs(finite))) or 1.0) if len(finite) else values
    matrix = pd.DataFrame(normalized).corr(min_periods=2).to_numpy().tolist() if normalized else []
    return json_safe({"rows": rows, "columns": columns, "total_cells": rows * columns, "missing_cells": missing,
                      "missing_percentage": 100 * missing / (rows * columns) if rows * columns else 0.0,
                      "duplicate_rows": int(df.duplicated().sum()) if columns else 0,
                      "memory_bytes": int(df.memory_usage(index=True, deep=True).sum()),
                      "type_distribution": dict(distribution), "empty_columns": empty, "constant_columns": constant,
                      "column_profiles": profiles, "correlation": {"columns": correlation_columns, "matrix": matrix},
                      "warnings": (["Correlation limited to the first 50 numeric columns."] if len(numeric_columns) > 50 else []) + list(df.attrs.get("warnings", []))})


def _issue(category: str, column: str | None, ids: list, explanation: str, suggestion: str,
           confidence: float = 1.0, severity: str = "warning", method: str = "deterministic", human_review: bool = True) -> dict:
    key = hashlib.sha256(f"{category}:{column}".encode()).hexdigest()[:12]
    return {"id": f"{category}-{key}", "category": category, "column": column,
            "row_ids": [int(idx) for idx in ids[:_ROW_LIMIT]], "count": len(ids), "severity": severity,
            "method": method, "explanation": explanation, "confidence": confidence,
            "suggestion": suggestion, "human_review": human_review}


def quality(df: pd.DataFrame, domain_rules: dict | None = None) -> list[dict]:
    """Domain rules accept {'column': {'min': 0, 'max': 100}} (either bound).

    Also supports {'non_negative': ['column']} as an explicit minimum-zero rule.

    Fuzzy matching inspects at most 100 categories of <=100 characters, 4,950
    pairs per column, and returns at most 20 pairs. Findings are not corrections.
    """
    rules = {} if domain_rules is None else domain_rules
    if not isinstance(rules, dict):
        raise ValueError("Domain rules must be an object")
    if set(rules) - set(df.columns) - {"non_negative"}:
        raise ValueError("Domain rules refer to unknown columns")
    non_negative = rules.get("non_negative", [])
    if not isinstance(non_negative, list) or any(not isinstance(name, str) or name not in df.columns for name in non_negative):
        raise ValueError("non_negative must contain existing column names")
    issues = []

    def add(category, column, mask, explanation, suggestion, **kwargs):
        ids = list(df.index[np.asarray(mask, dtype=bool)])
        if ids:
            issues.append(_issue(category, column, ids, explanation, suggestion, **kwargs))

    if len(df.columns):
        add("duplicate_rows", None, df.duplicated(keep="first"), "Rows exactly repeat earlier records; duplicates may still be legitimate.", "Review and select individual duplicate row IDs.")
    fingerprints = {}
    for name in df.columns:
        series = df[name]
        hashed = hashlib.sha256(pd.util.hash_pandas_object(series, index=False).values.tobytes()).digest()
        for previous in fingerprints.get(hashed, []):
            if series.equals(df[previous]):
                add("duplicate_columns", name, np.ones(len(df), dtype=bool), f"Column exactly duplicates {previous!r} including null positions.", "Review whether this column can be removed.")
                break
        fingerprints.setdefault(hashed, []).append(name)
        text_mask = series.map(lambda value: isinstance(value, str))
        text = series.map(lambda value: value if isinstance(value, str) else "")
        add("missing_values", name, series.isna(), "Actual null cells are present; textual null tokens are counted separately.", "Review missingness before selecting an imputation strategy.")
        add("empty_strings", name, text_mask & text.eq(""), "Zero-length string cells are present.", "Normalize the empty-string token only if it represents missing data.")
        add("whitespace", name, text_mask & text.ne(text.str.strip()), "Leading or trailing whitespace is present.", "Preview trimming whitespace.")
        candidates = [numeric_candidate(value.strip(), preserve_identifiers=False) if isinstance(value, str) else None for value in series]
        number_mask = np.array([value is not None for value in candidates])
        add("numeric_strings", name, number_mask, "Text cells can be represented as numbers. Leading zeros and textual formatting would be lost on conversion.", "Review identifiers and precision before explicit numeric conversion.", confidence=0.9, method="conservative decimal parsing")
        nonempty = text_mask & text.str.strip().ne("")
        numeric_context = (number_mask.sum() >= 2 and number_mask.sum() / max(int(nonempty.sum()), 1) >= 0.8) or bool(_NUMERIC_NAME.search(str(name)))
        if numeric_context and not is_numeric_dtype(series.dtype):
            add("invalid_numeric", name, nonempty & ~number_mask, "Some cells cannot be safely converted to finite numbers in a numeric-like column.", "Review invalid values; do not coerce them to null without approval.", confidence=0.8, method="numeric context heuristic")
        dates, _, invalid, ambiguous = _date_details(series, str(name))
        if dates:
            if invalid:
                issues.append(_issue("invalid_dates", name, invalid, "Date-like column contains invalid or unrecognized date values; no ambiguous date order was guessed.", "Select an explicit date format and review failures.", 0.85, method="strict date parsing"))
            if len(dates["formats"]) > 1 or ambiguous:
                ids = [idx for idx, value in series.items() if not pd.isna(value)]
                issues.append(_issue("mixed_date_formats", name, ids, "Multiple date formats or ambiguous day/month order require review.", "Confirm date order and convert with an explicit format.", 0.8, method="date shape heuristic"))
        text_values = sorted(set(value for value in series if isinstance(value, str)))
        groups = {}
        for value in text_values:
            groups.setdefault(value.casefold(), []).append(value)
        variants = {value for group in groups.values() if len(group) > 1 for value in group}
        add("casing", name, text.isin(variants) & text_mask, "Categories differ only in letter case.", "Select a casing convention only if case is not meaningful.", confidence=0.95)
        fuzzy_values = [value for value in text_values if 3 <= len(value) <= 100][:100]
        pairs = []
        for left, right in combinations(fuzzy_values, 2):
            if left.strip().casefold() == right.strip().casefold():
                continue
            similarity = ratio(left.casefold(), right.casefold())
            if 85 <= similarity < 100:
                pairs.append((left, right))
                if len(pairs) == 20:
                    break
        if pairs:
            selected = {value for pair in pairs for value in pair}
            add("spelling_variations", name, text.isin(selected) & text_mask,
                f"Potential spelling variants (bounded lexical sample, not confirmed errors): {pairs!r}.",
                "Approve an explicit category mapping; never merge solely on similarity.", confidence=0.6, severity="info", method="bounded fuzzy similarity >=85%")
        if series.nunique(dropna=True) == 1:
            add("constant_columns", name, series.notna(), "Every non-null value is identical.", "Keep unless the column has no business meaning.", severity="info")
        sentinel = series.map(lambda value: str(value).strip().casefold() in _SENTINELS if not pd.isna(value) else False)
        add("sentinel_values", name, sentinel, "Values resemble common missing-data sentinels but may be legitimate.", "Select exact tokens to normalize after domain review.", confidence=0.65, method="sentinel heuristic")
        if re.search(r"e.?mail", str(name), re.I) or (text_mask.any() and text.str.contains("@", regex=False).sum() >= max(1, int(text_mask.sum()) * 0.8)):
            email_ok = text.str.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", na=False)
            add("invalid_email", name, series.notna() & ~email_ok, "Email-like value fails a basic shape check; this does not verify ownership or delivery.", "Review the address against its source.", confidence=0.85, method="email shape heuristic")
        if re.search(r"phone|mobile|telephone|fax", str(name), re.I):
            def phone_ok(value):
                value = str(value)
                return bool(re.fullmatch(r"\+?[0-9 ()\-.]+", value)) and 7 <= len(re.sub(r"\D", "", value)) <= 15
            add("invalid_phone", name, series.notna() & ~series.map(phone_ok), "Phone-like value fails a broad 7–15 digit shape check; local formats and extensions can be legitimate.", "Review with country-specific domain knowledge.", confidence=0.6, method="phone shape heuristic")
        column_rule = rules.get(name, {}) if name != "non_negative" else {}
        if not isinstance(column_rule, dict) or set(column_rule) - {"min", "max", "non_negative"}:
            raise ValueError("Column domain rules support only min, max and non_negative")
        if "non_negative" in column_rule and not isinstance(column_rule["non_negative"], bool):
            raise ValueError("non_negative must be a boolean")
        lower, upper = column_rule.get("min"), column_rule.get("max")
        for bound in (lower, upper):
            if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (int, float)) or not math.isfinite(bound)):
                raise ValueError("Domain bounds must be finite numbers")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("Domain minimum exceeds maximum")
        if name in non_negative or column_rule.get("non_negative") is True or lower is not None:
            lower = lower if lower is not None else 0
            values = _number_values(series)
            if len(values):
                add("negative_values", name, np.isfinite(values) & (values < lower), f"Values violate the explicit domain minimum {lower}.", "Review the confirmed domain-rule violation; do not infer replacement values.", severity="error", method="explicit domain rule")
        if upper is not None:
            values = _number_values(series)
            if len(values):
                add("domain_range", name, np.isfinite(values) & (values > upper), f"Values violate the explicit domain maximum {upper}.", "Review the confirmed domain-rule violation; do not infer replacement values.", severity="error", method="explicit domain rule")
        def shape(value):
            if not isinstance(value, str):
                return type(value).__name__
            return re.sub(r"\d+", "9", re.sub(r"[A-Za-z]+", "A", value.strip()))
        shapes = Counter(shape(value) for value in series.dropna() if str(value).strip())
        if 1 < len(shapes) <= 20:
            dominant, count = shapes.most_common(1)[0]
            if count / sum(shapes.values()) >= 0.6:
                add("mixed_formats", name, series.map(lambda value: not pd.isna(value) and bool(str(value).strip()) and shape(value) != dominant),
                    "Minority values have different text/type shapes; free text may legitimately vary.", "Review inconsistent shapes without automatically rewriting them.", confidence=0.6, severity="info", method="majority shape heuristic")
    return json_safe(issues)


def recommendations(df: pd.DataFrame, issues: list[dict] | None = None) -> list[dict]:
    issues = quality(df) if issues is None else issues
    result = []
    for issue in issues:
        category, column = issue["category"], issue["column"]
        series = df[column] if column in df.columns else None
        operation, loss = None, False
        affected = issue["count"]
        if category == "whitespace":
            operation = {"kind": "trim", "column": column, "params": {}}
            loss = True
        elif category in {"empty_strings", "sentinel_values"} and series is not None:
            tokens = sorted({value for value in series if isinstance(value, str) and (value == "" if category == "empty_strings" else value.strip().casefold() in _SENTINELS)})
            if tokens:
                selected_tokens = tokens[:50]
                operation = {"kind": "normalize_missing", "column": column, "params": {"tokens": selected_tokens}}
                affected = int(series.isin(selected_tokens).sum())
                loss = True
        elif category == "duplicate_rows":
            operation = {"kind": "drop_duplicates", "column": None, "params": {"row_ids": issue["row_ids"]}}
            loss = True
        elif category == "numeric_strings" and series is not None:
            parsed = [numeric_candidate(value) for value in series.dropna()]
            if parsed and all(value is not None for value in parsed):
                integers = [value for value in parsed if isinstance(value, int)]
                mixed_precision_loss = len(integers) != len(parsed) and any(abs(value) > 2**53 for value in integers)
                signed_unsigned_conflict = bool(integers) and min(integers) < 0 and max(integers) >= 2**63
                if not mixed_precision_loss and not signed_unsigned_conflict:
                    operation = {"kind": "to_numeric", "column": column, "params": {"coerce": False}}
                    loss = True
        elif category == "casing":
            operation = {"kind": "case", "column": column, "params": {"mode": "lower"}}
            affected = int(series.map(lambda value: isinstance(value, str) and value.lower() != value).sum())
            loss = True
        elif category == "missing_values" and series is not None and series.notna().any():
            strategy = "median" if is_numeric_dtype(series.dtype) and not is_bool_dtype(series.dtype) else "mode"
            if strategy == "median":
                if not np.isfinite(_number_values(series)).any():
                    continue
                if is_integer_dtype(series.dtype) and any(abs(int(value)) > 2**53 for value in series.dropna()):
                    strategy = "mode"
            operation = {"kind": "fill_missing", "column": column, "params": {"strategy": strategy}}
        if operation:
            result.append({"id": f"rec-{issue['id']}", "reason": issue["explanation"], "column": column,
                           "operation": operation, "affected_records": len(issue["row_ids"]) if category == "duplicate_rows" else affected,
                           "expected_benefit": issue["suggestion"], "potential_data_loss": loss,
                           "tradeoffs": "Preview and approve the selected scope. Formatting, legitimate categories, distributions or record multiplicity may be meaningful.",
                           "requires_approval": True})
    for column in df.columns:
        raw = _number_values(df[column])
        count = int(np.isinf(raw).sum())
        if count:
            result.append({"id": f"rec-infinity-{column}", "reason": "Infinite values cannot be used in finite statistics.", "column": column,
                           "operation": {"kind": "handle_infinity", "column": column, "params": {}},
                           "affected_records": count, "expected_benefit": "Replace explicitly reviewed infinities with null.",
                           "potential_data_loss": True, "tradeoffs": "Infinite values may have legitimate meaning.", "requires_approval": True})
    return json_safe(result)


def anomalies(df: pd.DataFrame, method: str, columns: list[str], threshold: float | None = None) -> dict:
    if method not in ("iqr", "mad", "isolation_forest"):
        raise ValueError("Unknown anomaly method")
    if not isinstance(columns, list) or not columns or any(not isinstance(name, str) for name in columns) or len(columns) != len(set(columns)) or any(name not in df.columns for name in columns):
        raise ValueError("Select distinct existing numeric columns")
    if any(not is_numeric_dtype(df[name].dtype) or is_bool_dtype(df[name].dtype) for name in columns):
        raise ValueError("Anomaly detection requires numeric, non-boolean columns")
    if method != "isolation_forest":
        threshold = (1.5 if method == "iqr" else 3.5) if threshold is None else threshold
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("Threshold must be finite and positive")
    result = {"method": method, "findings": [], "warnings": []}
    if method == "isolation_forest":
        if len(columns) < 2 or len(columns) > 20:
            raise ValueError("Isolation Forest requires 2–20 selected numeric features")
        if any(_ID_NAME.search(name) for name in columns):
            raise ValueError("Identifier, code and phone columns are not suitable model features")
        if len(df) > 50_000:
            raise ValueError("Isolation Forest is limited to 50,000 rows; no silent subsampling")
        matrix = np.column_stack([_number_values(df[name]) for name in columns])
        valid = np.isfinite(matrix).all(axis=1)
        finite = matrix[valid]
        if len(finite) < 10:
            result["warnings"].append("At least 10 complete finite rows are required for Isolation Forest.")
            return result
        if not valid.all():
            result["warnings"].append(f"Excluded {int((~valid).sum())} rows with null or infinite features; no imputation was performed.")
        scale = np.max(np.abs(finite), axis=0)
        scale[scale == 0] = 1.0
        normalized = finite / scale
        if np.any(np.ptp(normalized, axis=0) <= np.finfo(float).eps):
            result["warnings"].append("Constant or numerically indistinguishable features: select variable features.")
            return result
        from sklearn.ensemble import IsolationForest
        model = IsolationForest(n_estimators=100, max_samples=min(256, len(finite)), contamination="auto", random_state=42, n_jobs=1)
        flagged = model.fit_predict(normalized) == -1
        positions = np.flatnonzero(valid)[flagged]
        result["findings"].append({"column": None, "columns": columns, "row_ids": [int(df.index[p]) for p in positions[:200]],
                                   "values": [json_safe(df.iloc[p][columns].tolist()) for p in positions[:200]], "count": len(positions),
                                   "thresholds": {"decision_function": 0, "contamination": "auto", "random_state": 42},
                                   "explanation": "Opt-in multivariate Isolation Forest with finite complete cases and bounded features; anomalies are not confirmed data errors."})
        return json_safe(result)
    for column in columns:
        raw = _number_values(df[column])
        valid = np.isfinite(raw)
        values = raw[valid]
        if not valid.all():
            result["warnings"].append(f"{column}: excluded {int((~valid).sum())} null or infinite values.")
        if len(values) < 4:
            result["warnings"].append(f"{column}: at least four finite values are required.")
            continue
        scale = float(np.max(np.abs(values))) or 1.0
        scaled = values / scale
        with np.errstate(all="ignore"):
            if method == "iqr":
                q1, q3 = np.quantile(scaled, [0.25, 0.75])
                spread = q3 - q1
                low, high = q1 - threshold * spread, q3 + threshold * spread
                selected = (scaled < low) | (scaled > high)
                thresholds = {"lower": _finite(low * scale), "upper": _finite(high * scale), "q1": _finite(q1 * scale), "q3": _finite(q3 * scale), "multiplier": threshold}
                explanation = "Finite values outside Q1 − multiplier×IQR or Q3 + multiplier×IQR. Statistical outliers, not confirmed errors."
                if spread == 0:
                    result["warnings"].append(f"{column}: IQR is zero; only values outside the coincident quartiles can be flagged.")
            else:
                median = np.median(scaled)
                mad = np.median(np.abs(scaled - median))
                thresholds = {"median": _finite(median * scale), "mad": _finite(mad * scale), "modified_z_threshold": threshold}
                if mad == 0:
                    result["warnings"].append(f"{column}: MAD is zero; modified Z-scores are undefined, so no values are flagged.")
                    selected = np.zeros(len(values), dtype=bool)
                else:
                    selected = np.abs(0.6744897501960817 * (scaled - median) / mad) > threshold
                explanation = "Absolute modified Z-score = 0.67448975×|value−median|/MAD. Statistical outliers, not confirmed errors."
        positions = np.flatnonzero(valid)[selected]
        result["findings"].append({"column": column, "row_ids": [int(df.index[p]) for p in positions[:200]],
                                   "values": [json_safe(df.iloc[p][column]) for p in positions[:200]], "count": len(positions),
                                   "thresholds": thresholds, "explanation": explanation})
    return json_safe(result)
