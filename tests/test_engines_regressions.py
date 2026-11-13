"""Data-integrity regressions discovered during integration and edge-case review."""
import csv
import io
import json
import warnings

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from backend.analysis import anomalies, profile, quality
from backend.cleaning import apply_operation, preview_operation
from backend.exports import export_data
from backend.ingestion import load_file


def frame(data):
    result = pd.DataFrame(data)
    result.index.name = "__row_id__"
    return result


def test_parent_benchmark_numeric_column_with_twenty_structural_nulls():
    rng = np.random.default_rng(42)
    source = pd.DataFrame({"amount": rng.normal(100, 20, 2000), "label": ["synthetic"] * 2000})
    source.loc[:19, "amount"] = np.nan
    with np.errstate(invalid="ignore"):
        data = source.to_csv(index=False).encode()
    df = load_file(data, "benchmark.csv", {"header": 0}, {})
    assert pd.api.types.is_numeric_dtype(df["amount"])
    assert profile(df)["missing_cells"] == 20
    assert df["amount"].isna().sum() == 20
    np.testing.assert_allclose(df["amount"].to_numpy(dtype=float, na_value=np.nan), source["amount"], equal_nan=True, rtol=0, atol=0)
    assert anomalies(df, "iqr", ["amount"])["method"] == "iqr"
    assert anomalies(df, "mad", ["amount"])["method"] == "mad"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_quote_metadata_distinguishes_null_empty_and_literal_tokens(newline):
    text = newline.join(['a,b,c,d,e', ',"",NULL,NA,001', '"multi' + newline + 'line","","""",,tail', ''])
    df = load_file(text.encode(), "x.csv", {"delimiter": ","}, {})
    assert pd.isna(df.iloc[0, 0])
    assert df.iloc[0, 1] == ""
    assert df.iloc[0, 2:5].tolist() == ["NULL", "NA", "001"]
    assert df.iloc[1, 0] == "multi" + newline + "line"
    assert df.iloc[1, 1] == ""
    assert df.iloc[1, 2] == '"'
    assert pd.isna(df.iloc[1, 3])


def test_csv_export_reingestion_retains_structural_nulls_and_quoted_empty_strings():
    source = frame({"x": pd.Series(["", None, "NULL", "001"], dtype="string"), "number": pd.Series([1, None, 3, 4], dtype="Int64")})
    encoded = export_data(source, "csv")[0]
    loaded = load_file(encoded, "export.csv", {}, {})
    assert_frame_equal(source, loaded, check_names=True)
    assert b'""' in encoded


def test_empty_physical_lines_do_not_desynchronize_quote_metadata():
    data = b'\r\na,b\r\n\r\n,""\r\n\r\n"",\r\n'
    df = load_file(data, "x.csv", {"delimiter": ","}, {})
    assert len(df) == 2
    assert pd.isna(df.iloc[0, 0]) and df.iloc[0, 1] == ""
    assert df.iloc[1, 0] == "" and pd.isna(df.iloc[1, 1])


def test_preview_infinity_is_not_misrepresented_as_null_before_change():
    result = preview_operation(frame({"x": [np.inf, -np.inf, None]}), {"kind": "handle_infinity", "column": "x", "params": {}})
    assert result["affected_cells"] == 2
    assert [change["before"] for change in result["changes"]] == ["Infinity", "-Infinity"]
    assert all(change["after"] is None for change in result["changes"])
    json.dumps(result, allow_nan=False)


def test_fill_preview_counts_only_value_changes_not_numeric_dtype_widening():
    result = preview_operation(frame({"x": pd.Series([1, 2, None], dtype="Int64")}), {"kind": "fill_missing", "column": "x", "params": {"strategy": "mean"}})
    assert result["affected_cells"] == 1
    assert result["changes"] == [{"row_id": 2, "column": "x", "before": None, "after": 1.5}]


def test_domain_minimum_and_maximum_and_validation():
    df = frame({"amount": [-1, 0, 100, 101, None]})
    rules = {"amount": {"min": 0, "max": 100}}
    issues = quality(df, rules)
    assert next(item for item in issues if item["category"] == "negative_values")["row_ids"] == [0]
    assert next(item for item in issues if item["category"] == "domain_range")["row_ids"] == [3]
    for invalid in ({"missing": {"min": 0}}, {"amount": {"max": np.inf}}, {"amount": {"min": 10, "max": 0}}, {"amount": {"min": True}}, {"amount": {"bad": 1}}):
        with pytest.raises(ValueError):
            quality(df, invalid)


def test_xlsx_export_is_byte_deterministic():
    df = frame({"x": [1, 2, None], "text": ["a", "b", "c"]})
    assert export_data(df, "xlsx")[0] == export_data(df, "xlsx")[0]


def test_precision_loss_and_overflow_in_narrow_integer_cleaning_rejected_or_promoted():
    df = frame({"x": pd.Series([127, None], dtype="Int8")})
    filled = apply_operation(df, {"kind": "fill_missing", "column": "x", "params": {"strategy": "constant", "value": 1000}})
    assert filled["x"].tolist() == [127, 1000]
    with pytest.raises(ValueError):
        apply_operation(df, {"kind": "fill_missing", "column": "x", "params": {"strategy": "constant", "value": 2**100}})


def test_precision_loss_runtime_warning_is_not_allowed_for_near_constant_profiles():
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = profile(frame({"x": [1., 1., 1., 1. + 1e-15]}))
    json.dumps(result, allow_nan=False)


def test_csv_writer_quoted_delimiters_and_escaped_quotes_stay_lossless():
    original = frame({"x": pd.Series(['a,b', 'say "hi"', '', None], dtype="string"), "y": ["a", "b", "c", "d"]})
    content = export_data(original, "csv")[0]
    parsed = load_file(content, "x.csv", {}, {})
    assert parsed["x"].fillna("MISSING").tolist() == original["x"].fillna("MISSING").tolist()
    assert len(list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))) == 5
