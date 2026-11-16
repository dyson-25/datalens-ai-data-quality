import json
import math

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from backend.analysis import anomalies, profile, quality, recommendations


def frame(data):
    df = pd.DataFrame(data)
    df.index = pd.Index(range(10, 10 + len(df) * 2, 2), name="__row_id__")
    return df


def test_known_numeric_statistics_and_correlation():
    df = frame({"x": [1, 2, 3, 4], "y": [2, 4, 6, 8], "missing": [None] * 4})
    result = profile(df)
    numeric = result["column_profiles"][0]["numeric"]
    assert result["rows"] == 4 and result["columns"] == 3
    assert result["total_cells"] == 12 and result["missing_cells"] == 4
    assert result["missing_percentage"] == pytest.approx(100 / 3)
    for name, value in {"min": 1, "max": 4, "mean": 2.5, "median": 2.5, "variance": 5 / 3, "std": math.sqrt(5 / 3), "q1": 1.75, "q3": 3.25, "iqr": 1.5, "skewness": 0, "kurtosis": -1.2}.items():
        assert numeric[name] == pytest.approx(value)
    assert sum(numeric["histogram"]["counts"]) == 4
    assert result["correlation"]["columns"] == ["x", "y"]
    assert result["correlation"]["matrix"][0][1] == pytest.approx(1)
    assert result["empty_columns"] == ["missing"]
    assert "__row_id__" not in json.dumps(result)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("values", [
    [], [None], [np.nan, np.nan], [float("inf"), -float("inf"), np.nan],
    [1e308, -1e308, 1e308, -1e308], [1e308] * 4,
    [1, 1 + 1e-14, 1 + 2e-14, 1 + 3e-14], [1e-300, 2e-300, 3e-300],
])
def test_numeric_edge_cases_are_strict_json_and_warning_safe(values):
    df = frame({"x": pd.Series(values, dtype="float64")})
    result = profile(df)
    json.dumps(result, allow_nan=False)
    numeric = result["column_profiles"][0]["numeric"]
    assert numeric["infinity_count"] == sum(math.isinf(value) for value in values if isinstance(value, float))
    assert sum(numeric["histogram"]["counts"]) == sum(pd.notna(value) and math.isfinite(value) for value in values)


def test_nullable_integer_boolean_and_datetime_profiles():
    df = frame({"amount": pd.Series([1, None, 3], dtype="Int64"),
                "enabled": pd.Series([True, False, None], dtype="boolean"),
                "date": pd.to_datetime(["2024-01-01", None, "2024-01-03"])})
    result = profile(df)
    columns = {col["name"]: col for col in result["column_profiles"]}
    assert columns["enabled"]["semantic_type"] == "boolean"
    assert columns["enabled"]["numeric"] is None
    assert columns["date"]["dates"]["range_days"] == 2
    assert columns["amount"]["non_null_count"] == 2
    assert columns["amount"]["numeric"]["mean"] == 2


def test_rich_category_profile():
    df = frame({"category": ["Red", "red", " red ", "blue", "blue", None]})
    result = profile(df)["column_profiles"][0]
    assert result["distinct_count"] == 4
    assert result["common_values"][0] == {"value": "blue", "count": 2}
    categorical = result["categorical"]
    assert categorical["string_lengths"] == {"min": 3, "max": 5, "mean": 3.8}
    assert ["Red", "red"] in categorical["case_differences"]
    assert len(categorical["whitespace_variants"]) == 1


def test_mixed_supported_dates_distinguish_valid_invalid_ambiguous_missing():
    df = frame({"order_date": ["2026-09-04", "09/09/2026", "16/08/2026", "2026/10/02", "31/10/2026", "31-10-2026", "2026-13-04", "not-a-date", "04/09/2026", None, "29/02/2025"]})
    dates = profile(df)["column_profiles"][0]["dates"]
    assert (dates["valid_count"], dates["invalid_count"], dates["ambiguous_count"], dates["missing_count"]) == (6, 3, 1, 1)
    issues = {item["category"]: item for item in quality(df)}
    assert issues["invalid_dates"]["row_ids"] == [22, 24, 30]
    assert issues["ambiguous_dates"]["row_ids"] == [26]
    assert issues["mixed_date_formats"]["severity"] == "info"


def test_dates_conservative_ambiguity_and_invalid_values():
    df = frame({"date": ["2024-01-31", "31/01/2024", "01/02/2024", "2024-02-30", None],
                "identifier": ["001", "002", "003", "004", "005"]})
    result = profile(df)["column_profiles"][0]
    assert result["dates"]["valid_count"] == 2
    assert result["dates"]["invalid_count"] == 1
    assert result["dates"]["ambiguous_count"] == 1
    assert result["semantic_type"] != "date"
    assert profile(df)["column_profiles"][1]["semantic_type"] != "numeric_string"
    issues = {issue["category"]: issue for issue in quality(df) if issue["column"] == "date"}
    assert issues["invalid_dates"]["row_ids"] == [16]
    assert "mixed_date_formats" in issues


@pytest.mark.parametrize("category,data,rules,ids", [
    ("missing_values", {"x": [1, None]}, None, [12]),
    ("empty_strings", {"x": ["", "a"]}, None, [10]),
    ("whitespace", {"x": [" a", "b"]}, None, [10]),
    ("duplicate_rows", {"x": [1, 1]}, None, [12]),
    ("duplicate_columns", {"x": [1, 2], "y": [1, 2]}, None, [10, 12]),
    ("numeric_strings", {"x": ["1", "2"]}, None, [10, 12]),
    ("invalid_numeric", {"amount": ["1", "oops"]}, None, [12]),
    ("invalid_dates", {"date": ["2024-01-01", "bad"]}, None, [12]),
    ("mixed_date_formats", {"date": ["2024-01-01", "31/01/2024"]}, None, [10, 12]),
    ("casing", {"x": ["London", "london"]}, None, [10, 12]),
    ("spelling_variations", {"x": ["California", "Californa", "California", "California"]}, None, [10, 12, 14, 16]),
    ("constant_columns", {"x": ["fixed", "fixed"]}, None, [10, 12]),
    ("sentinel_values", {"x": ["null", "real"]}, None, [10]),
    ("invalid_email", {"email": ["a@example.test", "not-an-address"]}, None, [12]),
    ("invalid_phone", {"phone": ["+1 (202) 555-0123", "bad"]}, None, [12]),
    ("negative_values", {"amount": [1, -1]}, {"non_negative": ["amount"]}, [12]),
    ("mixed_formats", {"x": ["AB-123", "CD-456", "EF-789", "AB/123"]}, None, [16]),
])
def test_all_seventeen_quality_rules(category, data, rules, ids):
    df = frame(data)
    before = df.copy(deep=True)
    matches = [issue for issue in quality(df, rules) if issue["category"] == category]
    assert matches
    assert matches[0]["row_ids"] == ids
    assert matches[0]["count"] == len(ids)
    assert set(matches[0]) - {"mappings"} == {"id", "category", "column", "row_ids", "count", "severity", "method", "explanation", "confidence", "suggestion", "human_review"}
    assert 0 <= matches[0]["confidence"] <= 1
    assert_frame_equal(df, before)
    assert quality(df, rules) == quality(df, rules)


def test_negative_values_require_explicit_domain_rules():
    df = frame({"amount": [-2, 1]})
    assert not any(issue["category"] == "negative_values" for issue in quality(df))
    result = quality(df, {"amount": {"min": 0}})
    assert any(issue["category"] == "negative_values" and issue["count"] == 1 for issue in result)


def test_numeric_readiness_separates_invalid_missing_and_numeric_values():
    df = frame({"quantity": ["1", "2", "5", "two", "many", "-3", "0", None]})
    column = profile(df)["column_profiles"][0]
    readiness = column["numeric_conversion"]
    assert readiness["parseable_count"] == 5
    assert readiness["parseable_percentage"] == pytest.approx(500 / 7)
    assert readiness["invalid_count"] == 2 and readiness["missing_count"] == 1
    assert readiness["invalid_examples"] == [{"row_id": 16, "value": "two"}, {"row_id": 18, "value": "many"}]
    assert column["numeric"] is None


def test_discount_domain_rules_are_independent_of_statistical_fences():
    df = frame({"discount_pct": [-10, 0, 25, 50, 100, 125]})
    issues = quality(df, {"discount_pct": {"min": 0, "max": 100}})
    violations = [item for item in issues if item["method"] == "explicit domain rule"]
    assert {idx for item in violations for idx in item["row_ids"]} == {10, 20}
    assert all(item["severity"] == "error" for item in violations)


@pytest.mark.parametrize("name,values,rule,expected", [
    ("quantity", [-3, 0, 1, 2.5, 5], {"min": 1, "integer": True}, {10, 12, 16}),
    ("unit_price_inr", [-199, 0, 2324.56, 3310.08, 10], {"min": 0, "exclusive_min": True}, {10, 12}),
    ("delivery_days", [-4, 0, 4, 7.5, 180], {"min": 0, "integer": True}, {10, 16}),
    ("customer_rating", [0, 1, 2, 5, 6], {"min": 1, "max": 5}, {10, 18}),
])
def test_explicit_retail_domain_constraints(name, values, rule, expected):
    issues = quality(frame({name: values}), {name: rule})
    assert {idx for issue in issues if issue["method"] == "explicit domain rule" for idx in issue["row_ids"]} == expected


def test_bounded_quality_samples_keep_exact_total_counts():
    df = frame({"x": [None] * 1000})
    issue = next(issue for issue in quality(df) if issue["category"] == "missing_values")
    assert issue["count"] == 1000
    assert len(issue["row_ids"]) == 200
    assert issue["row_ids"][0] == 10


def test_fuzzy_sampling_is_bounded_and_deterministic():
    df = frame({"category": [f"California-{i:04}" for i in range(1000)]})
    first = quality(df)
    assert first == quality(df)
    assert not any(item["category"] == "spelling_variations" for item in first)


@pytest.mark.parametrize("name,values", [
    ("order_id", ["NS-00001", "NS-00002"]),
    ("label", ["NS-00001", "NS-00002"]),
    ("customer_email", ["alice@example.test", "alica@example.test"]),
    ("label", ["alice@example.test", "alica@example.test"]),
    ("phone", ["+919876543210", "+919876543211"]),
    ("customer_name", ["Caroline", "Carolyn"]),
    ("order_status", ["Completed", "Complete"]),
])
def test_fuzzy_excludes_structured_and_unsubstantiated_labels(name, values):
    assert not any(item["category"] == "spelling_variations" for item in quality(frame({name: values})))


def test_fuzzy_mapping_contains_explicit_review_evidence():
    df = frame({"region": ["California"] * 9 + ["Californa"]})
    issue = next(item for item in quality(df) if item["category"] == "spelling_variations")
    mapping = issue["mappings"][0]
    assert mapping["mapping"] == {"Californa": "California"}
    assert mapping["affected_records"] == 1
    assert 0.85 <= mapping["similarity"] < 1
    assert mapping["requires_approval"] is True
    assert issue["severity"] == "info"
    assert not any(item["operation"]["kind"] == "map_categories" for item in recommendations(df))


def test_recommendations_never_mutate_and_require_approval():
    df = frame({"x": [" a ", " a ", "", "NA"], "num": [1., np.inf, None, 2.]})
    before = df.copy(deep=True)
    result = recommendations(df)
    assert result
    assert all(item["requires_approval"] is True for item in result)
    assert any(item["operation"]["kind"] == "handle_infinity" for item in result)
    assert_frame_equal(df, before)
    json.dumps(result, allow_nan=False)


def test_identifiers_and_mixed_numbers_not_recommended_for_conversion():
    df = frame({"id": ["001", "002"], "amount": ["1", "bad"]})
    assert not any(item["operation"]["kind"] == "to_numeric" for item in recommendations(df))


@pytest.mark.parametrize("method", ["iqr", "mad"])
def test_statistical_anomalies_find_planted_value_with_stable_ids(method):
    df = frame({"value": [1., 2., 3., 4., 5., 6., 7., 100., None, np.inf]})
    before = df.copy(deep=True)
    result = anomalies(df, method, ["value"])
    finding = result["findings"][0]
    assert finding["row_ids"] == [24]
    assert finding["values"] == [100]
    assert finding["count"] == 1
    assert result["warnings"]
    assert_frame_equal(df, before)
    json.dumps(result, allow_nan=False)


def test_iqr_thresholds_are_known():
    result = anomalies(frame({"x": [1, 2, 3, 4]}), "iqr", ["x"])
    assert result["findings"][0]["thresholds"] == {"lower": -0.5, "upper": 5.5, "q1": 1.75, "q3": 3.25, "multiplier": 1.5}


@pytest.mark.parametrize("method", ["iqr", "mad"])
@pytest.mark.parametrize("values", [[1, 1, 1, 1], [1], [], [np.nan, np.inf], [1e308, -1e308, 1e308, -1e308]])
def test_anomaly_degenerate_inputs(method, values):
    result = anomalies(frame({"x": pd.Series(values, dtype=float)}), method, ["x"])
    json.dumps(result, allow_nan=False)
    assert all(item["count"] == 0 for item in result["findings"])


def test_zero_mad_does_not_invent_finite_scores():
    result = anomalies(frame({"x": [1, 1, 1, 1, 100]}), "mad", ["x"])
    assert result["findings"][0]["count"] == 0
    assert "MAD is zero" in result["warnings"][0]


@pytest.mark.parametrize("method,columns,threshold", [
    ("unknown", ["x"], None), ("iqr", [], None), ("iqr", ["x", "x"], None),
    ("iqr", ["missing"], None), ("iqr", ["text"], None), ("iqr", ["flag"], None),
    ("iqr", ["x"], -1), ("mad", ["x"], 0), ("mad", ["x"], True),
    ("mad", ["x"], np.inf), ("iqr", ["x"], np.nan),
])
def test_invalid_anomaly_requests(method, columns, threshold):
    df = frame({"x": [1, 2], "text": ["a", "b"], "flag": [True, False]})
    with pytest.raises(ValueError):
        anomalies(df, method, columns, threshold)


def test_opt_in_isolation_forest_deterministic_bounded_and_multivariate():
    rng = np.random.default_rng(42)
    df = frame({"height": np.r_[rng.normal(0, .1, 100), 100], "weight": np.r_[rng.normal(0, .1, 100), -100]})
    first = anomalies(df, "isolation_forest", ["height", "weight"])
    assert first == anomalies(df, "isolation_forest", ["height", "weight"])
    finding = first["findings"][0]
    assert int(df.index[-1]) in finding["row_ids"]
    assert finding["column"] is None
    assert all(len(value) == 2 for value in finding["values"])
    with pytest.raises(ValueError, match="Identifier"):
        anomalies(df.rename(columns={"height": "customer_id"}), "isolation_forest", ["customer_id", "weight"])
    with pytest.raises(ValueError, match="2–20"):
        anomalies(df, "isolation_forest", ["height"])
    large = frame({"a": range(50_001), "b": range(50_001)})
    with pytest.raises(ValueError, match="50,000"):
        anomalies(large, "isolation_forest", ["a", "b"])


def test_isolation_forest_excludes_incomplete_rows_and_constant_features():
    df = frame({"a": [1.] * 20, "b": list(range(19)) + [np.inf]})
    result = anomalies(df, "isolation_forest", ["a", "b"])
    assert result["findings"] == []
    assert len(result["warnings"]) == 2
