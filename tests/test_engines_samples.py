"""Synthetic demonstrations and final no-data-loss edge cases."""
import io
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from backend.analysis import anomalies, profile, quality, recommendations
from backend.cleaning import apply_operation, preview_operation
from backend.exports import export_data
from backend.ingestion import inspect_file, load_file


SAMPLES = Path(__file__).resolve().parents[1] / "sample_datasets"


def test_clean_synthetic_sample_preserves_identifiers_and_parquet():
    df = load_file((SAMPLES / "clean_reference.csv").read_bytes(), "clean.csv", {}, {})
    assert len(df) == 20
    assert df["record_id"].iloc[0] == "00001"
    assert df.index.name == "__row_id__"
    assert profile(df)["missing_cells"] == 0
    buffer = io.BytesIO()
    df.to_parquet(buffer)
    assert_frame_equal(df, pd.read_parquet(io.BytesIO(buffer.getvalue())))


def test_quality_synthetic_sample_has_planted_findings():
    df = load_file((SAMPLES / "quality_issues.csv").read_bytes(), "quality.csv", {}, {})
    categories = {item["category"] for item in quality(df, {"amount": {"min": 0}})}
    assert {"missing_values", "empty_strings", "whitespace", "duplicate_rows", "duplicate_columns", "invalid_numeric", "invalid_dates", "mixed_date_formats", "casing", "constant_columns", "sentinel_values", "invalid_email", "invalid_phone", "negative_values"} <= categories


def test_anomaly_synthetic_sample_has_planted_outlier_and_null():
    df = load_file((SAMPLES / "statistical_anomalies.csv").read_bytes(), "anomaly.csv", {}, {})
    assert profile(df)["missing_cells"] == 1
    for method in ("iqr", "mad"):
        result = anomalies(df, method, ["height", "weight"])
        assert all(100 in finding["row_ids"] for finding in result["findings"])
        assert len(result["findings"]) == 2


def test_multisheet_synthetic_workbook_and_malformed_example():
    data = (SAMPLES / "multi_sheet.xlsx").read_bytes()
    inspected = inspect_file(data, "sheets.xlsx", {})
    assert inspected["sheets"] == ["Clean reference", "Quality issues"]
    assert len(load_file(data, "sheets.xlsx", {"sheet": "Clean reference"}, {})) == 20
    assert len(load_file(data, "sheets.xlsx", {"sheet": "Quality issues"}, {})) == 21
    with pytest.raises(ValueError):
        load_file((SAMPLES / "malformed.csv").read_bytes(), "malformed.csv", {}, {})


@pytest.mark.parametrize("kind,params,expected", [
    ("trim", {}, ["A", "B", None]),
    ("case", {"mode": "lower"}, [" a ", "b", None]),
    ("map_categories", {"mapping": {" A ": "renamed", "B": "renamed"}}, ["renamed", "renamed", None]),
])
def test_categorical_text_operations_do_not_lose_new_labels(kind, params, expected):
    df = pd.DataFrame({"x": pd.Categorical([" A ", "B", None])})
    df.index.name = "__row_id__"
    before = df.copy(deep=True)
    operation = {"kind": kind, "column": "x", "params": params}
    changed = apply_operation(df, operation)
    assert changed["x"].astype(object).where(changed["x"].notna(), None).tolist() == expected
    assert preview_operation(df, operation)["affected_cells"] == (1 if kind == "trim" else 2)
    assert_frame_equal(df, before)


@pytest.mark.parametrize("kind,params", [
    ("case", {"mode": []}),
    ("fill_missing", {"strategy": []}),
    ("outliers", {"action": [], "row_ids": [0]}),
])
def test_unhashable_operation_choices_raise_contract_valueerror(kind, params):
    with pytest.raises(ValueError):
        apply_operation(pd.DataFrame({"x": [1]}), {"kind": kind, "column": "x", "params": params})


@pytest.mark.parametrize("prefix", ["\ufeff", " \ufeff\t", "\u200b", "\x01"])
def test_csv_formula_escaping_includes_invisible_prefixes(prefix):
    data = export_data(pd.DataFrame({"x": [prefix + "=1+1"]}), "csv")[0]
    assert ("'" + prefix + "=1+1").encode() in data


def test_numeric_profile_extrema_keep_large_integer_precision():
    df = pd.DataFrame({"x": pd.Series([2**63 + 1, 2**63 + 3], dtype="UInt64")})
    numeric = profile(df)["column_profiles"][0]["numeric"]
    assert numeric["min"] == 2**63 + 1
    assert numeric["max"] == 2**63 + 3


@pytest.mark.parametrize("values", [["9007199254740993", "1.5"], ["-1", "9223372036854775808"]])
def test_precision_losing_numeric_conversion_is_not_recommended(values):
    assert not any(item["operation"]["kind"] == "to_numeric" for item in recommendations(pd.DataFrame({"x": values})))


def test_recommendation_counts_actual_casing_scope_and_large_integer_mode():
    df = pd.DataFrame({"text": ["ABC", "ABC", "abc"], "integer": pd.Series([2**63 + 1, 2**63 + 3, None], dtype="UInt64")})
    df.index.name = "__row_id__"
    proposed = recommendations(df)
    casing = next(item for item in proposed if item["operation"]["kind"] == "case")
    assert casing["affected_records"] == preview_operation(df, casing["operation"])["affected_rows"] == 2
    fill = next(item for item in proposed if item["operation"]["kind"] == "fill_missing")
    assert fill["operation"]["params"]["strategy"] == "mode"
    assert apply_operation(df, fill["operation"])["integer"].iloc[-1] == 2**63 + 1


@pytest.mark.parametrize("rules", [[], "", False])
def test_non_mapping_domain_rules_rejected(rules):
    with pytest.raises(ValueError):
        quality(pd.DataFrame({"x": [1]}), rules)
