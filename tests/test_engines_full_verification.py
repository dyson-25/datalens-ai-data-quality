"""FV case IDs: independent expected values, executable replay, and read-only samples."""

import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook
from pandas.testing import assert_frame_equal, assert_series_equal

from backend.analysis import anomalies, json_safe, profile, quality, recommendations
from backend.cleaning import apply_operation, preview_operation
from backend.exports import export_data, generate_code, report_data
from backend.ingestion import inspect_file, load_file


SAMPLES = Path(__file__).resolve().parents[1] / "sample_datasets"


def frame(values, dtype="string"):
    result = pd.DataFrame({"x": pd.Series(values, dtype=dtype)})
    result.index = pd.Index(range(101, 101 + len(result) * 3, 3), name="__row_id__")
    result.attrs = {"warnings": ["source notice"], "source": {"tokens": ["unchanged"]}}
    return result


def operation(kind, params=None, column="x"):
    return {"kind": kind, "column": column, "params": params or {}}


CLEANING_CASES = [
    pytest.param(
        ["\u2003 A \t", "B", None],
        "string",
        operation("trim"),
        ["A", "B", None],
        "string",
        [101, 104, 107],
        1,
        id="FV-C01-trim-unicode",
    ),
    pytest.param(
        ["NA", "na", " NA", "", None],
        "string",
        operation("normalize_missing", {"tokens": ["NA", ""]}),
        [None, "na", " NA", None, None],
        "string",
        [101, 104, 107, 110, 113],
        2,
        id="FV-C02-exact-missing-tokens",
    ),
    pytest.param(
        ["a", "a", "a", "b"],
        "string",
        operation("drop_duplicates", {"row_ids": [107]}, None),
        ["a", "a", "b"],
        "string",
        [101, 104, 110],
        1,
        id="FV-C03-selected-duplicate",
    ),
    pytest.param(
        [" 001 ", "2", None],
        "string",
        operation("to_numeric"),
        [1, 2, None],
        "Int64",
        [101, 104, 107],
        2,
        id="FV-C04-numeric-int",
    ),
    pytest.param(
        ["1.25", "bad", None],
        "string",
        operation("to_numeric", {"coerce": True}),
        [1.25, None, None],
        "Float64",
        [101, 104, 107],
        2,
        id="FV-C05-numeric-coerce",
    ),
    pytest.param(
        [str(2**64 - 1), None],
        "string",
        operation("to_numeric"),
        [2**64 - 1, None],
        "UInt64",
        [101, 104],
        1,
        id="FV-C06-numeric-uint64",
    ),
    pytest.param(
        ["29/02/2024", "01/03/2024", None],
        "string",
        operation("to_date", {"format": "%d/%m/%Y"}),
        [pd.Timestamp("2024-02-29"), pd.Timestamp("2024-03-01"), None],
        "datetime64[ns]",
        [101, 104, 107],
        2,
        id="FV-C07-date-exact",
    ),
    pytest.param(
        ["29/02/2023", "29/02/2024", None],
        "string",
        operation("to_date", {"format": "%d/%m/%Y", "coerce": True}),
        [None, pd.Timestamp("2024-02-29"), None],
        "datetime64[ns]",
        [101, 104, 107],
        2,
        id="FV-C08-date-coerce",
    ),
    pytest.param(
        ["2024-01-01T01:00:00+0100", None],
        "string",
        operation("to_date", {"format": "%Y-%m-%dT%H:%M:%S%z"}),
        [pd.Timestamp("2024-01-01", tz="UTC"), None],
        "datetime64[ns, UTC]",
        [101, 104],
        1,
        id="FV-C09-date-utc",
    ),
    pytest.param(
        [1, 2, None],
        "Int64",
        operation("fill_missing", {"strategy": "mean"}),
        [1, 2, 1.5],
        "Float64",
        [101, 104, 107],
        1,
        id="FV-C10-fill-mean",
    ),
    pytest.param(
        [1, 9, 2, None],
        "Int64",
        operation("fill_missing", {"strategy": "median"}),
        [1, 9, 2, 2],
        "Int64",
        [101, 104, 107, 110],
        1,
        id="FV-C11-fill-median",
    ),
    pytest.param(
        ["z", "a", None],
        "string",
        operation("fill_missing", {"strategy": "mode"}),
        ["z", "a", "z"],
        "string",
        [101, 104, 107],
        1,
        id="FV-C12-fill-mode-first-seen",
    ),
    pytest.param(
        [None, "a"],
        "string",
        operation("fill_missing", {"strategy": "constant", "value": ""}),
        ["", "a"],
        "string",
        [101, 104],
        1,
        id="FV-C13-fill-empty-text",
    ),
    pytest.param(
        [True, None],
        "boolean",
        operation("fill_missing", {"strategy": "constant", "value": False}),
        [True, False],
        "boolean",
        [101, 104],
        1,
        id="FV-C14-fill-boolean",
    ),
    pytest.param(
        [pd.Timestamp("2024-01-01"), None],
        "datetime64[ns]",
        operation("fill_missing", {"strategy": "constant", "value": "2024-02-29"}),
        [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-29")],
        "datetime64[ns]",
        [101, 104],
        1,
        id="FV-C15-fill-date",
    ),
    pytest.param(
        [127, None],
        "Int8",
        operation("fill_missing", {"strategy": "constant", "value": 1000}),
        [127, 1000],
        "Int64",
        [101, 104],
        1,
        id="FV-C16-fill-widen-integer",
    ),
    pytest.param(
        ["AbC", "same", None],
        "string",
        operation("case", {"mode": "lower"}),
        ["abc", "same", None],
        "string",
        [101, 104, 107],
        1,
        id="FV-C17-case-lower",
    ),
    pytest.param(
        ["AbC", "SAME", None],
        "string",
        operation("case", {"mode": "upper"}),
        ["ABC", "SAME", None],
        "string",
        [101, 104, 107],
        1,
        id="FV-C18-case-upper",
    ),
    pytest.param(
        ["aBC deF", "Same", None],
        "string",
        operation("case", {"mode": "title"}),
        ["Abc Def", "Same", None],
        "string",
        [101, 104, 107],
        1,
        id="FV-C19-case-title",
    ),
    pytest.param(
        ["a", "b", "c", "d", None],
        "string",
        operation("map_categories", {"mapping": {"a": "b", "b": "c", "c": None}}),
        ["b", "c", None, "d", None],
        "string",
        [101, 104, 107, 110, 113],
        3,
        id="FV-C20-map-simultaneous-null",
    ),
    pytest.param(
        [np.inf, -np.inf, 3, None],
        "Float64",
        operation("handle_infinity"),
        [None, None, 3, None],
        "Float64",
        [101, 104, 107, 110],
        2,
        id="FV-C21-infinity-both-signs",
    ),
    pytest.param(
        [-10, 10, 99, None],
        "Int64",
        operation("outliers", {"row_ids": [101, 104, 110], "action": "clip", "lower": -2.5, "upper": 2.5}),
        [-2.5, 2.5, 99, None],
        "Float64",
        [101, 104, 107, 110],
        2,
        id="FV-C22-clip-selected-null",
    ),
    pytest.param(
        [-10, 10, 99, None],
        "Int64",
        operation("outliers", {"row_ids": [104], "action": "remove"}),
        [-10, 99, None],
        "Int64",
        [101, 107, 110],
        1,
        id="FV-C23-remove-selected",
    ),
    pytest.param(
        ["a", None], "string", operation("drop_column"), None, None, [101, 104], 2, id="FV-C24-drop-column"
    ),
]


@pytest.mark.parametrize("values,dtype,op,expected,expected_dtype,ids,affected", CLEANING_CASES)
def test_cleaning_known_results_preview_and_executable_replay(
    values, dtype, op, expected, expected_dtype, ids, affected
):
    source = frame(values, dtype)
    before = source.copy(deep=True)
    attributes = copy.deepcopy(source.attrs)
    op_before = copy.deepcopy(op)
    preview = preview_operation(source, op)
    actual = apply_operation(source, op)
    assert actual.index.tolist() == ids
    assert preview["affected_cells"] == preview["affected_rows"] == affected
    assert preview["rows_removed"] == len(source) - len(actual)
    assert preview["rows_added"] == 0
    assert preview["metrics_before"]["rows"] == len(source)
    assert preview["metrics_after"]["rows"] == len(actual)
    if expected is None:
        assert actual.shape == (len(ids), 0)
    else:
        target = pd.Series(expected, dtype=expected_dtype, index=pd.Index(ids, name="__row_id__"), name="x")
        assert_series_equal(actual["x"], target)
        buffer = io.BytesIO()
        actual.to_parquet(buffer)
        assert_frame_equal(actual, pd.read_parquet(io.BytesIO(buffer.getvalue())))
    namespace = {}
    code = generate_code([op], "python")
    exec(compile(code, "<datalens-generated-reference>", "exec"), namespace)
    assert namespace["OPERATIONS"] == [op]
    assert_frame_equal(namespace["replay"](source), actual)
    assert_frame_equal(source, before)
    assert source.attrs == attributes and op == op_before
    actual.attrs["source"]["tokens"].append("changed only in result")
    assert source.attrs == attributes
    json.dumps(preview, allow_nan=False)


@pytest.mark.parametrize("ordered", [False, True], ids=["FV-B01-unordered-mode", "FV-B02-ordered-mode"])
def test_categorical_mode_ties_follow_observed_order(ordered):
    source = frame(
        pd.Categorical(["z", "a", None], categories=["unused", "a", "z"], ordered=ordered), "category"
    )
    actual = apply_operation(source, operation("fill_missing", {"strategy": "mode"}))
    assert actual["x"].tolist() == ["z", "a", "z"]
    assert source["x"].isna().tolist() == [False, False, True]


def test_categorical_mode_cannot_fill_from_unobserved_dictionary_labels():
    """FV-B04: a category dictionary is not a finite observation for imputation."""
    source = frame(pd.Categorical([None, None], categories=["unused", "a"]), "category")
    with pytest.raises(ValueError, match="empty column"):
        apply_operation(source, operation("fill_missing", {"strategy": "mode"}))
    assert source["x"].isna().all()


def test_categorical_common_values_exclude_unused_and_ties_follow_observed_order():
    """FV-B03: category dictionary order is not record occurrence order."""
    source = frame(pd.Categorical(["z", "a", None], categories=["unused", "a", "z"]), "category")
    column = profile(source)["column_profiles"][0]
    expected = [{"value": "z", "count": 1}, {"value": "a", "count": 1}]
    assert column["common_values"] == expected
    assert column["categorical"]["frequencies"] == expected
    assert column["categorical"]["unique_categories"] == 2


@pytest.mark.parametrize(
    "dtype,values,op",
    [
        pytest.param("string", ["1", "bad"], operation("to_numeric"), id="FV-V01-invalid-numeric"),
        pytest.param(
            "string",
            [str(2**53 + 1), "1.5"],
            operation("to_numeric", {"coerce": True}),
            id="FV-V02-mixed-precision",
        ),
        pytest.param("string", ["-1", str(2**63)], operation("to_numeric"), id="FV-V03-signed-unsigned"),
        pytest.param(
            "string", ["2024/01/01"], operation("to_date", {"format": "%Y-%m-%d"}), id="FV-V04-date-separator"
        ),
        pytest.param(
            "Int64",
            [2**53 + 1, None],
            operation("fill_missing", {"strategy": "median"}),
            id="FV-V05-large-median",
        ),
        pytest.param(
            "UInt64",
            [2**64 - 1, None],
            operation("fill_missing", {"strategy": "constant", "value": -1}),
            id="FV-V06-fill-overflow",
        ),
        pytest.param(
            "Float64",
            [1.5, None],
            operation("fill_missing", {"strategy": "constant", "value": 2**53 + 1}),
            id="FV-V07-float-rounding",
        ),
        pytest.param(
            "boolean",
            [True, None],
            operation("fill_missing", {"strategy": "constant", "value": 1}),
            id="FV-V08-boolean-type",
        ),
        pytest.param(
            "Float64",
            [np.inf, None],
            operation("fill_missing", {"strategy": "mean"}),
            id="FV-V09-no-finite-mean",
        ),
        pytest.param(
            "string", [None, None], operation("fill_missing", {"strategy": "mode"}), id="FV-V10-empty-mode"
        ),
        pytest.param(
            "datetime64[ns, UTC]",
            [pd.Timestamp("2024-01-01", tz="UTC"), None],
            operation("fill_missing", {"strategy": "constant", "value": "2024-01-02"}),
            id="FV-V11-timezone-fill",
        ),
        pytest.param(
            "string",
            ["a", "a"],
            operation("drop_duplicates", {"row_ids": [101]}, None),
            id="FV-V12-first-duplicate",
        ),
        pytest.param(
            "Int64",
            [1, 2],
            operation("outliers", {"row_ids": [999], "action": "remove"}),
            id="FV-V13-stale-row-id",
        ),
    ],
)
def test_rejections_are_atomic(dtype, values, op):
    source = frame(values, dtype)
    before = source.copy(deep=True)
    for function in (apply_operation, preview_operation):
        with pytest.raises(ValueError):
            function(source, op)
        assert_frame_equal(source, before)
        assert source.attrs == before.attrs


@pytest.mark.parametrize(
    "index",
    [
        pd.Index([1, 1], name="__row_id__"),
        pd.Index(["1", "2"], name="__row_id__"),
        pd.Index([1, 2], name="wrong"),
        pd.Index([True, False], name="__row_id__"),
    ],
    ids=["FV-V14-duplicate-ids", "FV-V15-string-ids", "FV-V16-index-name", "FV-V17-bool-ids"],
)
def test_stable_index_contract(index):
    source = frame([" a ", "b"])
    source.index = index
    with pytest.raises(ValueError, match="stable integer"):
        apply_operation(source, operation("trim"))


def test_multistep_pipeline_replay_export_and_raw_preservation():
    """FV-P01: filtering never resets IDs; reference code executes against baseline."""
    raw = b"id,label,amount,date,unused\n001, A ,1,2024-01-01,x\n001, A ,1,2024-01-01,x\n002,NA,bad,invalid,y\n003,B,100,2024-01-03,z\n"
    digest = hashlib.sha256(raw).hexdigest()
    source = load_file(raw, "pipeline.csv", {}, {})
    baseline = source.copy(deep=True)
    ops = [
        operation("drop_duplicates", {"row_ids": [1]}, None),
        operation("trim", column="label"),
        operation("normalize_missing", {"tokens": ["NA"]}, "label"),
        operation("fill_missing", {"strategy": "constant", "value": "unknown"}, "label"),
        operation("case", {"mode": "lower"}, "label"),
        operation("map_categories", {"mapping": {"b": "beta"}}, "label"),
        operation("to_numeric", {"coerce": True}, "amount"),
        operation("fill_missing", {"strategy": "median"}, "amount"),
        operation("outliers", {"action": "clip", "row_ids": [3], "upper": 10}, "amount"),
        operation("to_date", {"format": "%Y-%m-%d", "coerce": True}, "date"),
        operation("drop_column", column="unused"),
    ]
    result = source
    for op in ops:
        result = apply_operation(result, op)
    assert result.index.tolist() == [0, 2, 3]
    assert result["id"].tolist() == ["001", "002", "003"]
    assert result["label"].tolist() == ["a", "unknown", "beta"]
    assert result["amount"].tolist() == [1, 50.5, 10]
    assert result["date"].isna().tolist() == [False, True, False]
    namespace = {}
    exec(compile(generate_code(ops, "python"), "<verified-pipeline>", "exec"), namespace)
    assert_frame_equal(namespace["replay"](source), result)
    outliers = namespace["inspect_outliers"](result, ["amount"])
    assert set(outliers) == {"iqr", "mad"}
    for extension in ("csv", "xlsx"):
        content = export_data(result, extension)[0]
        loaded = load_file(content, "result." + extension, {}, {})
        assert loaded["id"].tolist() == ["001", "002", "003"]
        assert loaded["amount"].tolist() == [1, 50.5, 10]
        assert loaded["date"].iloc[0] == "2024-01-01T00:00:00"
    assert_frame_equal(source, baseline)
    assert hashlib.sha256(raw).hexdigest() == digest


@pytest.mark.parametrize(
    "values,dtype,semantic",
    [
        pytest.param([1, None, 3], "Int64", "numeric", id="FV-S01-numeric"),
        pytest.param([True, None, False], "boolean", "boolean", id="FV-S02-boolean"),
        pytest.param(["1", "2", None], "string", "numeric_string", id="FV-S03-numeric-string"),
        pytest.param(["2024-01-01", "2024-01-02", None], "string", "date", id="FV-S04-date-string"),
        pytest.param([pd.Timestamp("2024-01-01"), None], "datetime64[ns]", "date", id="FV-S05-date-storage"),
        pytest.param(["001", "002", None], "string", "categorical", id="FV-S06-identifier-not-number"),
        pytest.param(["01/02/2024", "02/03/2024"], "string", "categorical", id="FV-S07-ambiguous-date"),
        pytest.param([f"text-{i}" for i in range(60)], "string", "text", id="FV-S08-free-text"),
    ],
)
def test_semantic_profiles_are_review_only(values, dtype, semantic):
    source = frame(values, dtype)
    before = source.copy(deep=True)
    result = profile(source)
    assert result["column_profiles"][0]["semantic_type"] == semantic
    assert result["column_profiles"][0]["storage_type"] == str(source["x"].dtype)
    assert_frame_equal(source, before)
    assert result["warnings"] == ["source notice"]
    json.dumps(result, allow_nan=False)


def test_profile_quantiles_correlation_and_finite_denominators():
    """FV-S09: infinities excluded from statistics, not counted as missing."""
    source = pd.DataFrame(
        {
            "x": pd.Series([-2, 0, 2, 4, np.inf, -np.inf, None], dtype="Float64"),
            "y": pd.Series([4, 0, -4, -8, None, None, None], dtype="Float64"),
        }
    )
    p = profile(source)
    x = p["column_profiles"][0]["numeric"]
    for name, expected in {
        "min": -2,
        "max": 4,
        "mean": 1,
        "median": 1,
        "variance": 20 / 3,
        "q1": -0.5,
        "q3": 2.5,
        "iqr": 3,
        "negative_count": 1,
        "zero_count": 1,
        "finite_count": 4,
        "infinity_count": 2,
    }.items():
        assert x[name] == pytest.approx(expected)
    assert x["percentiles"] == pytest.approx(
        {"1": -1.94, "5": -1.7, "25": -0.5, "50": 1, "75": 2.5, "95": 3.7, "99": 3.94}
    )
    assert sum(x["histogram"]["counts"]) == 4
    assert p["missing_cells"] == 4
    assert p["correlation"]["matrix"][0][1] == pytest.approx(-1)


def test_profile_date_comparisons_normalize_only_for_summary():
    """FV-S10: mixed offsets compare as instants without changing source text."""
    source = frame(["2024-01-01T01:00:00+01:00", "2024-01-02T00:00:00Z", "bad", "01/02/2024", None])
    source.columns = ["order_date"]
    before = source.copy(deep=True)
    dates = profile(source)["column_profiles"][0]["dates"]
    assert dates["valid_count"] == 2 and dates["invalid_count"] == dates["ambiguous_count"] == 1
    assert dates["range_days"] == 1
    assert dates["min"] == "2024-01-01T00:00:00+00:00"
    assert_frame_equal(source, before)


def test_profile_correlation_and_frequency_caps_are_explicit():
    """FV-S11: bounded summaries retain true cardinality and announced limits."""
    source = pd.DataFrame({f"n{i}": [1, 2, 3] for i in range(51)})
    result = profile(source)
    assert result["correlation"]["columns"] == [f"n{i}" for i in range(50)]
    assert result["warnings"] == ["Correlation limited to the first 50 numeric columns."]
    cat = profile(frame([f"value-{i}" for i in range(60)]))["column_profiles"][0]
    assert cat["distinct_count"] == 60
    assert len(cat["common_values"]) == 10
    assert len(cat["categorical"]["frequencies"]) == 50
    assert cat["categorical"]["frequencies_truncated"] is True


QUALITY_SAMPLE_CASES = [
    ("duplicate_rows", None, [20]),
    ("empty_strings", "region", [10]),
    ("whitespace", "region", [3, 8, 13, 18]),
    ("missing_values", "amount", [1]),
    ("negative_values", "amount", [8]),
    ("invalid_numeric", "quantity", [2, 9]),
    ("sentinel_values", "quantity", [9]),
    ("invalid_dates", "order_date", [3]),
    ("mixed_date_formats", "order_date", list(range(21))),
    ("invalid_email", "email", [6]),
    ("invalid_phone", "phone", [7]),
    ("constant_columns", "constant", list(range(21))),
    ("duplicate_columns", "category_code_copy", list(range(21))),
    ("mixed_formats", "category_code", [12]),
    ("casing", "region", [0, 2, 4, 5, 7, 9, 12, 14, 15, 17, 19, 20]),
    ("spelling_variations", "region", [i for i in range(21) if i != 10]),
    ("numeric_strings", "quantity", [i for i in range(21) if i not in (2, 9)]),
]


@pytest.mark.parametrize(
    "category,column,ids",
    QUALITY_SAMPLE_CASES,
    ids=[f"FV-Q{i + 1:02}-{item[0]}" for i, item in enumerate(QUALITY_SAMPLE_CASES)],
)
def test_sample_quality_exact_record_ids(category, column, ids):
    source = load_file((SAMPLES / "quality_issues.csv").read_bytes(), "quality.csv", {}, {})
    before = source.copy(deep=True)
    findings = quality(source, {"amount": {"min": 0}})
    item = next(item for item in findings if item["category"] == category and item["column"] == column)
    assert item["row_ids"] == ids and item["count"] == len(ids)
    assert item["human_review"] is True
    assert 0 <= item["confidence"] <= 1
    assert_frame_equal(source, before)


def test_domain_maximum_is_explicit_and_findings_not_corrections():
    """FV-Q18: upper bound adds an eighteenth quality category."""
    source = frame([-1, 0, 100, 101, None], "Int64")
    before = source.copy(deep=True)
    assert not any(x["category"] in {"negative_values", "domain_range"} for x in quality(source))
    findings = quality(source, {"x": {"min": 0, "max": 100}})
    assert next(x for x in findings if x["category"] == "negative_values")["row_ids"] == [101]
    assert next(x for x in findings if x["category"] == "domain_range")["row_ids"] == [110]
    assert_frame_equal(source, before)


def test_recommendation_counts_match_preview_and_all_require_approval():
    """FV-Q19: every recommendation in the sample is executable and count-accurate."""
    source = load_file((SAMPLES / "quality_issues.csv").read_bytes(), "quality.csv", {}, {})
    before = source.copy(deep=True)
    proposals = recommendations(source)
    assert proposals
    for proposal in proposals:
        assert proposal["requires_approval"] is True
        assert (
            proposal["affected_records"] == preview_operation(source, proposal["operation"])["affected_rows"]
        )
        assert proposal["tradeoffs"] and proposal["expected_benefit"]
    assert_frame_equal(source, before)


def test_recommendation_duplicate_cap_matches_selected_not_total():
    """FV-Q20: bounded selection proposes 200 IDs, not all 299 duplicates."""
    source = frame(["a"] * 300)
    issue = next(x for x in quality(source) if x["category"] == "duplicate_rows")
    assert issue["count"] == 299 and len(issue["row_ids"]) == 200
    proposal = next(x for x in recommendations(source) if x["operation"]["kind"] == "drop_duplicates")
    assert proposal["affected_records"] == 200
    assert preview_operation(source, proposal["operation"])["rows_removed"] == 200


@pytest.mark.parametrize(
    "method,column,ids",
    [
        ("iqr", "height", [30, 100]),
        ("iqr", "weight", [39, 100]),
        ("mad", "height", [100]),
        ("mad", "weight", [100]),
    ],
    ids=["FV-A01-iqr-height", "FV-A02-iqr-weight", "FV-A03-mad-height", "FV-A04-mad-weight"],
)
def test_sample_anomalies_exact_ids_and_independent_calculation(method, column, ids):
    source = load_file((SAMPLES / "statistical_anomalies.csv").read_bytes(), "anomalies.csv", {}, {})
    before = source.copy(deep=True)
    result = anomalies(source, method, [column])
    finding = result["findings"][0]
    assert finding["row_ids"] == ids and finding["count"] == len(ids)
    values = source[column].to_numpy(dtype=float, na_value=np.nan)
    valid = np.isfinite(values)
    finite = values[valid]
    if method == "iqr":
        q1, q3 = np.quantile(finite, [0.25, 0.75])
        low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        mask = (finite < low) | (finite > high)
        assert finding["thresholds"]["lower"] == pytest.approx(low)
        assert finding["thresholds"]["upper"] == pytest.approx(high)
    else:
        median = np.median(finite)
        mad = np.median(abs(finite - median))
        mask = 0.6744897501960817 * abs(finite - median) / mad > 3.5
        assert finding["thresholds"]["median"] == pytest.approx(median)
        assert finding["thresholds"]["mad"] == pytest.approx(mad)
    assert source.index[valid][mask].tolist() == ids
    assert_frame_equal(source, before)


def test_anomaly_sample_truncation_preserves_exact_count():
    """FV-A05: 200 returned values are a sample of 300 identified anomalies."""
    source = frame([0.0] * 1000 + [100.0] * 300, "Float64")
    finding = anomalies(source, "iqr", ["x"])["findings"][0]
    assert finding["count"] == 300
    assert finding["row_ids"] == source.index[1000:1200].tolist()
    assert finding["values"] == [100.0] * 200


def test_isolation_forest_sample_is_repeatable_without_imputation():
    """FV-A06: planted bivariate anomaly found, incomplete row excluded."""
    source = load_file((SAMPLES / "statistical_anomalies.csv").read_bytes(), "anomalies.csv", {}, {})
    before = source.copy(deep=True)
    result = anomalies(source, "isolation_forest", ["height", "weight"])
    assert result == anomalies(source, "isolation_forest", ["height", "weight"])
    assert 100 in result["findings"][0]["row_ids"]
    assert 101 not in result["findings"][0]["row_ids"]
    assert result["warnings"] == [
        "Excluded 1 rows with null or infinite features; no imputation was performed."
    ]
    assert result["findings"][0]["thresholds"]["random_state"] == 42
    assert_frame_equal(source, before)


@pytest.mark.parametrize(
    "method", ["iqr", "mad"], ids=["FV-A07-iqr-strict-boundary", "FV-A08-mad-strict-boundary"]
)
def test_anomaly_threshold_boundary_is_strict(method):
    source = frame([0, 1, 2, 3, 4], "Int64")
    threshold = 0.5 if method == "iqr" else 2 * 0.6744897501960817
    result = anomalies(source, method, ["x"], threshold)
    assert result["findings"][0]["count"] == 0


@pytest.mark.parametrize(
    "extension", ["csv", "xlsx"], ids=["FV-E01-csv-values-types", "FV-E02-xlsx-values-types"]
)
def test_exports_exact_contents_and_types(extension):
    source = pd.DataFrame(
        {
            "identifier": pd.Series(["001", "", None], dtype="string"),
            "integer": pd.Series([123, 2**63 + 1, None], dtype="UInt64"),
            "decimal": pd.Series([1.25, 1.2345678901234567, None], dtype="Float64"),
            "flag": pd.Series([True, False, None], dtype="boolean"),
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", None], utc=True),
            "number": [-3.0, np.inf, -np.inf],
        }
    )
    source.index.name = "__row_id__"
    before = source.copy(deep=True)
    content, mime, suffix = export_data(source, extension)
    assert suffix == extension and mime
    if extension == "csv":
        assert content.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        assert rows == [
            list(source.columns),
            ["001", "123", "1.25", "True", "2024-01-01T00:00:00+00:00", "-3.0"],
            ["", str(2**63 + 1), "1.2345678901234567", "False", "2024-01-02T00:00:00+00:00", "Infinity"],
            ["", "", "", "", "", "'-Infinity"],
        ]
        loaded = load_file(content, "export.csv", {}, {})
        assert loaded["identifier"].iloc[1] == "" and pd.isna(loaded["identifier"].iloc[2])
        assert loaded["integer"].iloc[1] == 2**63 + 1
    else:
        book = load_workbook(io.BytesIO(content), data_only=False)
        sheet = book.active
        assert list(sheet.values) == [
            tuple(source.columns),
            ("001", 123, 1.25, True, "2024-01-01T00:00:00+00:00", -3),
            ("", str(2**63 + 1), "1.2345678901234567", False, "2024-01-02T00:00:00+00:00", "Infinity"),
            (None, None, None, None, None, "'-Infinity"),
        ]
        for coordinate, kind in {
            "A2": "s",
            "B2": "n",
            "B3": "s",
            "C2": "n",
            "C3": "s",
            "D2": "b",
            "E2": "s",
            "F2": "n",
        }.items():
            assert sheet[coordinate].data_type == kind
        assert all(cell.data_type != "f" for row in sheet for cell in row)
        book.close()
    assert_frame_equal(source, before)


@pytest.mark.parametrize(
    "prefix",
    ["=", "+", "-", "@", "\t", "\r", "\n", " \u200b=", "\ufeff@", "\u200d+"],
    ids=[f"prefix-{i}" for i in range(10)],
)
@pytest.mark.parametrize("extension", ["csv", "xlsx"], ids=["FV-E03-csv-formula", "FV-E04-xlsx-formula"])
def test_export_formula_prefixes_in_headers_and_cells(prefix, extension):
    value = prefix + "1+1"
    source = pd.DataFrame({value: [value, "normal"]})
    content = export_data(source, extension)[0]
    if extension == "csv":
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    else:
        book = load_workbook(io.BytesIO(content), data_only=False)
        rows = list(book.active.values)
        assert all(cell.data_type != "f" for row in book.active for cell in row)
        book.close()
    assert rows[0][0] == rows[1][0] == "'" + value
    assert rows[2][0] == "normal"
    assert source.iloc[0, 0] == value and source.columns[0] == value


def test_xlsx_xml_special_characters_and_exact_text_boundary():
    """FV-E05: XML escaping retains literal markup, CR and maximum-length text."""
    source = pd.DataFrame({"x": ['<tag>& "quote"\rline', "a" * 32767]})
    content = export_data(source, "xlsx")[0]
    book = load_workbook(io.BytesIO(content), data_only=False)
    assert book.active["A2"].value == source.iloc[0, 0]
    assert book.active["A3"].value == "a" * 32767
    book.close()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert b"<f>" not in archive.read("xl/worksheets/sheet1.xml")


def test_reports_contain_full_strict_json_history_and_escaped_html():
    """FV-E06: complete report payload, not only MIME/name or successful download."""
    source = frame(["<b>literal</b>", None])
    p, issues = profile(source), quality(source)
    history = [{"operation": operation("trim"), "version": 2, "label": "</pre><b>literal</b>"}]
    payload = json.loads(report_data(p, issues, history, "json")[0])
    assert payload["profile"] == p and payload["issues"] == issues and payload["history"] == history
    assert "not confirmed errors" in payload["notice"]
    html = report_data(p, issues, history, "html")[0].decode()
    assert "<b>literal</b>" not in html
    assert "&lt;b&gt;literal&lt;/b&gt;" in html
    assert "Content-Security-Policy" in html and "default-src 'none'" in html
    assert json_safe([np.nan, np.inf, -np.inf, pd.NA, pd.NaT]) == [None, "Infinity", "-Infinity", None, None]


def test_sql_all_operations_are_labelled_and_unsupported_steps_not_cast():
    """FV-E07: SQL is reference-only; conversions intentionally have no translation."""
    ops = [case.values[2] for case in CLEANING_CASES]
    code = generate_code(ops, "sql")
    assert code == generate_code(ops, "sql")
    assert "reference only; never executed" in code and code.endswith("ROLLBACK;\n")
    for number, op in enumerate(ops, 1):
        block = code.split(f"-- Step {number}: {op['kind']}\n", 1)[1].split("-- Step ", 1)[0]
        if op["kind"] in {"to_numeric", "to_date"}:
            assert "NOT TRANSLATED" in block
            assert not any(line.startswith(("UPDATE", "ALTER", "DELETE")) for line in block.splitlines())
        else:
            assert any(line.startswith(("UPDATE", "ALTER", "DELETE")) for line in block.splitlines())
    assert code.count("NOT TRANSLATED") == 6
    assert "Python str.strip also handles Unicode" in code
    assert "Locale/Unicode casing" in code
    assert "target numeric type" in code
    assert 'AND "x" IS NOT NULL' in code


@pytest.mark.parametrize(
    "op",
    [
        operation("trim", column="bad\x00column"),
        operation("map_categories", {"mapping": {"bad\x00value": "ok"}}),
    ],
    ids=["FV-E08-sql-nul-identifier", "FV-E09-sql-nul-literal"],
)
def test_sql_rejects_unrepresentable_nul(op):
    with pytest.raises(ValueError, match="NUL"):
        generate_code([op], "sql")


@pytest.mark.parametrize(
    "filename,rows,columns,missing,duplicates",
    [
        ("clean_reference.csv", 20, 7, 0, 0),
        ("quality_issues.csv", 21, 10, 1, 1),
        ("statistical_anomalies.csv", 102, 3, 1, 0),
    ],
    ids=["FV-I01-clean-sample", "FV-I02-quality-sample", "FV-I03-anomaly-sample"],
)
def test_sample_ingestion_summary_and_source_bytes_unchanged(filename, rows, columns, missing, duplicates):
    path = SAMPLES / filename
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    inspected = inspect_file(raw, filename, {})
    source = load_file(raw, filename, {}, {})
    p = profile(source)
    assert (p["rows"], p["columns"], p["missing_cells"], p["duplicate_rows"]) == (
        rows,
        columns,
        missing,
        duplicates,
    )
    assert inspected["format"] == "csv" and inspected["delimiter"] == ","
    assert source.index.tolist() == list(range(rows)) and source.index.name == "__row_id__"
    buffer = io.BytesIO()
    source.to_parquet(buffer)
    assert_frame_equal(source, pd.read_parquet(io.BytesIO(buffer.getvalue())))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "sheet,csv_name",
    [("Clean reference", "clean_reference.csv"), ("Quality issues", "quality_issues.csv")],
    ids=["FV-I04-xlsx-clean", "FV-I05-xlsx-quality"],
)
def test_sample_workbook_every_cell_matches_documented_escaped_csv(sheet, csv_name):
    path = SAMPLES / "multi_sheet.xlsx"
    raw = path.read_bytes()
    source = load_file(raw, "multi.xlsx", {"sheet": sheet}, {})
    book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
    rows = list(book[sheet].values)
    book.close()
    assert list(source.columns) == list(rows[0])
    expected = load_file((SAMPLES / csv_name).read_bytes(), csv_name, {}, {})
    assert_frame_equal(source.drop(columns="phone"), expected.drop(columns="phone"), check_dtype=False)
    csv_rows = list(csv.reader(io.StringIO((SAMPLES / csv_name).read_text())))
    phone_position = csv_rows[0].index("phone")
    phones = [row[phone_position] for row in csv_rows[1:]]
    expected_phones = ["'" + value if value.startswith("+") else value for value in phones]
    assert source["phone"].tolist() == expected_phones
    assert [row[phone_position] for row in rows[1:]] == expected_phones
    assert path.read_bytes() == raw


def test_csv_inference_formatting_tradeoff_is_visible_in_inspection():
    """FV-I06: source retains +/decimal formatting; active numeric inference does not."""
    raw = b"number,phone,identifier,token\n1.00,+12025550001,001,NA\n"
    assert inspect_file(raw, "x.csv", {})["preview"][1] == ["1.00", "+12025550001", "001", "NA"]
    source = load_file(raw, "x.csv", {}, {})
    assert source.iloc[0].tolist() == [1, 12025550001, "001", "NA"]
    assert raw == b"number,phone,identifier,token\n1.00,+12025550001,001,NA\n"


def test_malformed_sample_rejected_without_alteration():
    """FV-I07: both inspection and load reject the bundled unterminated record."""
    path = SAMPLES / "malformed.csv"
    raw = path.read_bytes()
    for function in (lambda: inspect_file(raw, "bad.csv", {}), lambda: load_file(raw, "bad.csv", {}, {})):
        with pytest.raises(ValueError, match="Malformed CSV"):
            function()
    assert path.read_bytes() == raw
