"""Explicit, copy-on-write transformations; version restoration belongs to store.

No operation guesses tokens, date formats, mappings or selected row IDs. Lossy
conversions require coerce=True; numeric precision loss is rejected even then.
"""
from __future__ import annotations

import copy
import math
from datetime import datetime

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_integer_dtype, is_numeric_dtype

from .analysis import _date_value, json_safe, profile
from .ingestion import numeric_candidate

_PARAMS = {
    "trim": set(), "normalize_missing": {"tokens"}, "drop_duplicates": {"row_ids"},
    "to_numeric": {"coerce"}, "to_date": {"format", "coerce", "date_order"},
    "fill_missing": {"strategy", "value"}, "drop_column": set(), "case": {"mode"},
    "map_categories": {"mapping"}, "handle_infinity": set(),
    "outliers": {"row_ids", "action", "lower", "upper"},
}


def validate_operation(operation: dict) -> tuple[str, str | None, dict]:
    """Validate shape without a DataFrame (also used by reference-code exports)."""
    if not isinstance(operation, dict) or set(operation) - {"kind", "column", "params"}:
        raise ValueError("Unknown operation fields")
    kind, column, params = operation.get("kind"), operation.get("column"), operation.get("params", {})
    if not isinstance(kind, str) or kind not in _PARAMS:
        raise ValueError("Unknown cleaning operation")
    if not isinstance(params, dict) or set(params) - _PARAMS[kind]:
        raise ValueError("Unknown operation parameters")
    if kind != "drop_duplicates" and not isinstance(column, str):
        raise ValueError("Select a target column")
    if kind == "drop_duplicates" and column is not None:
        raise ValueError("Duplicate selection applies to whole rows; column must be null")
    if kind in {"drop_duplicates", "outliers"}:
        ids = params.get("row_ids")
        if not isinstance(ids, list) or not ids or any(isinstance(idx, bool) or not isinstance(idx, int) for idx in ids) or len(ids) != len(set(ids)):
            raise ValueError("Select a nonempty list of distinct integer row IDs")
    if kind == "normalize_missing":
        tokens = params.get("tokens")
        if not isinstance(tokens, list) or not tokens or any(not isinstance(token, str) for token in tokens):
            raise ValueError("Select exact string tokens to normalize")
    if kind in {"to_numeric", "to_date"} and not isinstance(params.get("coerce", False), bool):
        raise ValueError("coerce must be a boolean")
    if kind == "to_date":
        date_format = params.get("format")
        if not isinstance(date_format, str) or (date_format != "supported" and "%" not in date_format):
            raise ValueError("Date conversion requires an explicit strptime format or supported formats")
        if "date_order" in params and (date_format != "supported" or params["date_order"] not in {"day_first", "month_first"}):
            raise ValueError("Select day_first or month_first for supported formats")
    if kind == "case" and params.get("mode") not in ("lower", "upper", "title"):
        raise ValueError("Case mode must be lower, upper or title")
    if kind == "map_categories":
        mapping = params.get("mapping")
        if not isinstance(mapping, dict) or not mapping or any(not isinstance(key, str) or (value is not None and not isinstance(value, str)) for key, value in mapping.items()):
            raise ValueError("Category mapping must map string values to strings or null")
    if kind == "fill_missing":
        strategy = params.get("strategy")
        if strategy not in ("median", "mean", "mode", "constant"):
            raise ValueError("Unknown missing-value strategy")
        if strategy == "constant":
            value = params.get("value")
            if value is None or not isinstance(value, (str, bool, int, float)) or (isinstance(value, float) and not math.isfinite(value)):
                raise ValueError("Constant fill requires a non-null finite scalar value")
        elif "value" in params:
            raise ValueError("value is only valid for a constant fill")
    if kind == "outliers":
        action = params.get("action")
        if action not in ("remove", "clip"):
            raise ValueError("Outlier action must be remove or clip")
        if action == "remove" and ("lower" in params or "upper" in params):
            raise ValueError("Bounds are only valid for clipping")
        if action == "clip":
            low, high = params.get("lower"), params.get("upper")
            if low is None and high is None:
                raise ValueError("Clipping requires an explicit bound")
            for bound in (low, high):
                if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (int, float)) or not math.isfinite(bound)):
                    raise ValueError("Clipping bounds must be finite numbers")
            if low is not None and high is not None and low > high:
                raise ValueError("Lower clipping bound exceeds upper bound")
    return kind, column, params


def _numeric_conversion(series: pd.Series, coerce: bool) -> pd.Series:
    if is_numeric_dtype(series.dtype) and not is_bool_dtype(series.dtype):
        return series.copy(deep=True)
    values = []
    for value in series:
        if pd.isna(value):
            values.append(pd.NA)
            continue
        parsed = numeric_candidate(value.strip(), preserve_identifiers=False) if isinstance(value, str) else None
        if parsed is None:
            if not coerce:
                raise ValueError("Numeric conversion would lose invalid values or precision; review failures before enabling coerce")
            values.append(pd.NA)
        else:
            values.append(parsed)
    present = [value for value in values if value is not pd.NA]
    if all(isinstance(value, int) for value in present):
        low, high = (min(present), max(present)) if present else (0, 0)
        if low < 0 and high >= 2**63:
            raise ValueError("Signed and unsigned integers cannot share a lossless numeric dtype")
        dtype = "UInt64" if high >= 2**63 else "Int64"
    else:
        if any(isinstance(value, int) and abs(value) > 2**53 for value in present):
            raise ValueError("Mixed integer/decimal conversion would lose integer precision")
        dtype = "Float64"
    return pd.Series(values, index=series.index, name=series.name, dtype=dtype)


def _numeric_for_assignment(series: pd.Series, value: int | float) -> pd.Series:
    if not is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype):
        raise ValueError("This operation requires a numeric, non-boolean column")
    if is_integer_dtype(series.dtype):
        present = series.dropna()
        if isinstance(value, float) and not value.is_integer():
            if any(abs(int(item)) > 2**53 for item in present):
                raise ValueError("Fractional values would round existing large integers")
            return series.astype("Float64")
        # Use an explicitly wide nullable integer, never overflowing a narrow dtype.
        low = min(int(present.min()), int(value)) if len(present) else int(value)
        high = max(int(present.max()), int(value)) if len(present) else int(value)
        if low < -(2**63) or high >= 2**64 or (low < 0 and high >= 2**63):
            raise ValueError("Assignment cannot be represented without integer overflow")
        return series.astype("UInt64" if high >= 2**63 else "Int64")
    if isinstance(value, int) and abs(value) > 2**53:
        raise ValueError("Assignment would round a large integer in a floating-point column")
    return series.astype("Float64")


def _map_text(series: pd.Series, transform) -> pd.Series:
    mapped = series.map(transform)
    return mapped if isinstance(series.dtype, pd.CategoricalDtype) else mapped.astype(series.dtype)


def _fill(series: pd.Series, params: dict) -> pd.Series:
    strategy = params["strategy"]
    if not series.isna().any():
        return series.copy(deep=True)
    if strategy in {"mean", "median"}:
        if not is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype):
            raise ValueError("Mean and median fills require a numeric column")
        if is_integer_dtype(series.dtype) and any(abs(int(value)) > 2**53 for value in series.dropna()):
            raise ValueError("Floating-point imputation could round large integers; choose an explicit exact constant or mode")
        values = series.to_numpy(dtype=float, na_value=np.nan)
        values = values[np.isfinite(values)]
        if not len(values):
            raise ValueError("Cannot compute an imputation value without finite observations")
        scale = float(np.max(np.abs(values))) or 1.0
        value = float((np.mean(values / scale) if strategy == "mean" else np.median(values / scale)) * scale)
    elif strategy == "mode":
        # Categorical dictionaries include unused labels and impose category order.
        observed = series.astype(object) if isinstance(series.dtype, pd.CategoricalDtype) else series
        counts = observed.value_counts(dropna=True, sort=False)
        if counts.empty:
            raise ValueError("Cannot calculate mode of an empty column")
        # Ties use first occurrence, not an unstable category sort.
        value = counts.index[int(np.argmax(counts.to_numpy()))]
        if isinstance(value, np.generic):
            value = value.item()
    else:
        value = params["value"]
    if is_bool_dtype(series.dtype):
        if not isinstance(value, bool):
            raise ValueError("Boolean columns require a boolean fill")
        return series.fillna(value)
    if is_numeric_dtype(series.dtype):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Numeric fill must be finite and numeric")
        return _numeric_for_assignment(series, value).fillna(value)
    if is_datetime64_any_dtype(series.dtype):
        try:
            value = pd.Timestamp(value)
            if pd.isna(value):
                raise ValueError("Missing timestamp")
            if getattr(series.dtype, "tz", None) != value.tzinfo:
                raise ValueError("Timezone mismatch")
            return series.fillna(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Date fill must be a compatible valid timestamp") from exc
    if not isinstance(value, str):
        raise ValueError("Text columns require a string fill to preserve their type")
    return series.fillna(value)


def apply_operation(df: pd.DataFrame, operation: dict) -> pd.DataFrame:
    kind, column, params = validate_operation(operation)
    if not df.index.is_unique or df.index.name != "__row_id__" or any(isinstance(idx, bool) or not isinstance(idx, (int, np.integer)) for idx in df.index):
        raise ValueError("Dataset must have unique stable integer __row_id__ index values")
    if column is not None and column not in df.columns:
        raise ValueError("Unknown target column")
    selected = params.get("row_ids", [])
    if any(idx not in df.index for idx in selected):
        raise ValueError("Selected row IDs are not present in this version")
    result = df.copy(deep=True)
    result.attrs = copy.deepcopy(df.attrs)
    if kind == "drop_duplicates":
        duplicates = set(df.index[df.duplicated(keep="first")])
        if not set(selected).issubset(duplicates):
            raise ValueError("Only selected duplicate records after the first occurrence may be removed")
        return result.drop(index=selected)
    if kind == "drop_column":
        return result.drop(columns=[column])
    series = result[column]
    try:
        if kind == "trim":
            result[column] = _map_text(series, lambda value: value.strip() if isinstance(value, str) else value)
        elif kind == "normalize_missing":
            result[column] = series.mask(series.map(lambda value: isinstance(value, str) and value in params["tokens"]), pd.NA)
        elif kind == "to_numeric":
            result[column] = _numeric_conversion(series, params.get("coerce", False))
        elif kind == "to_date":
            values = []
            for value in series:
                if pd.isna(value):
                    values.append(pd.NaT)
                    continue
                if params["format"] == "supported":
                    parsed, _, ambiguous = _date_value(value)
                    if ambiguous:
                        if not params.get("date_order"):
                            raise ValueError("Ambiguous dates require an explicit day/month order, even with coerce enabled")
                        separator = "/" if "/" in value else "-"
                        order = "%d{0}%m{0}%Y" if params["date_order"] == "day_first" else "%m{0}%d{0}%Y"
                        parsed = datetime.strptime(value, order.format(separator))
                    if parsed is None and not params.get("coerce", False):
                        raise ValueError("Date conversion contains invalid values; correct them or explicitly approve conversion to null")
                    values.append(parsed if parsed is not None else pd.NaT)
                    continue
                try:
                    # strptime prevents pandas accepting a different date separator.
                    if not isinstance(value, str):
                        raise ValueError("Source date conversion requires text")
                    values.append(datetime.strptime(value, params["format"]))
                except (ValueError, TypeError):
                    if not params.get("coerce", False):
                        raise ValueError("Date conversion failed for the selected exact format") from None
                    values.append(pd.NaT)
            # UTC gives a single Parquet-compatible dtype for explicit timezone formats.
            utc = params["format"] == "supported" or "%z" in params["format"] or "%Z" in params["format"]
            result[column] = pd.Series(pd.to_datetime(values, errors="coerce" if params.get("coerce", False) else "raise", utc=utc), index=series.index)
        elif kind == "fill_missing":
            result[column] = _fill(series, params)
        elif kind == "case":
            result[column] = _map_text(series, lambda value: getattr(value, params["mode"])() if isinstance(value, str) else value)
        elif kind == "map_categories":
            mapping = params["mapping"]
            result[column] = _map_text(series, lambda value: mapping.get(value, value) if isinstance(value, str) else value)
        elif kind == "handle_infinity":
            if not is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype):
                raise ValueError("Infinity handling requires a numeric column")
            result[column] = series.mask(np.isinf(series.to_numpy(dtype=float, na_value=np.nan)), pd.NA)
        elif kind == "outliers":
            if not is_numeric_dtype(series.dtype) or is_bool_dtype(series.dtype):
                raise ValueError("Outlier operations require a numeric column")
            if params["action"] == "remove":
                return result.drop(index=selected)
            low, high = params.get("lower"), params.get("upper")
            for bound in (low, high):
                if bound is not None:
                    series = _numeric_for_assignment(series, bound)
            result[column] = series
            result.loc[selected, column] = series.loc[selected].clip(lower=low, upper=high)
    except (TypeError, OverflowError) as exc:
        raise ValueError("Operation is incompatible with this column's values or storage type") from exc
    return result


def preview_operation(df: pd.DataFrame, operation: dict) -> dict:
    after = apply_operation(df, operation)
    removed_ids = set(df.index) - set(after.index)
    added_ids = set(after.index) - set(df.index)
    all_ids = df.index.append(after.index[~after.index.isin(df.index)])
    all_columns = list(df.columns) + [name for name in after.columns if name not in df.columns]
    old_rows, new_rows = all_ids.isin(df.index), all_ids.isin(after.index)
    affected = old_rows != new_rows
    cells, coordinates = 0, []
    for column_position, column in enumerate(all_columns):
        old_exists = old_rows & (column in df.columns)
        new_exists = new_rows & (column in after.columns)
        if column in df.columns and column in after.columns:
            old, new = df[column].reindex(all_ids), after[column].reindex(all_ids)
            # Object comparisons avoid pandas date/string coercion during comparison.
            same = old.isna() & new.isna()
            comparable = old.notna() & new.notna()
            same.loc[comparable] = old.loc[comparable].astype(object).eq(new.loc[comparable].astype(object)).to_numpy(dtype=bool)
            changed = (old_exists != new_exists) | (old_exists & new_exists & ~same.to_numpy(dtype=bool))
        else:
            changed = old_exists != new_exists
        cells += int(changed.sum())
        affected |= changed
        # At most 200 candidates per column, then a deterministic row-major sample.
        coordinates.extend((int(position), column_position) for position in np.flatnonzero(changed)[:200])
    changes = []
    for row_position, column_position in sorted(coordinates)[:200]:
        row_id, column = all_ids[row_position], all_columns[column_position]
        old = df.at[row_id, column] if row_id in df.index and column in df.columns else None
        new = after.at[row_id, column] if row_id in after.index and column in after.columns else None
        changes.append({"row_id": int(row_id), "column": column, "before": json_safe(old), "after": json_safe(new)})
    return {"operation": copy.deepcopy(operation), "affected_cells": cells, "affected_rows": int(affected.sum()),
            "rows_removed": len(removed_ids), "rows_added": len(added_ids), "changes": changes,
            "changes_truncated": cells > len(changes), "no_changes": df.equals(after),
            "schema_changed": not df.dtypes.equals(after.dtypes),
            "metrics_before": profile(df), "metrics_after": profile(after)}
