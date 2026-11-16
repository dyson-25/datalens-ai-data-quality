import ast
import csv
import io
import json

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook
from pandas.testing import assert_frame_equal

from backend.analysis import profile, quality
from backend.cleaning import apply_operation, preview_operation
from backend.exports import export_data, generate_code, report_data


def frame(data):
    df = pd.DataFrame(data)
    df.index = pd.Index(range(10, 10 + len(df) * 2, 2), name="__row_id__")
    return df


def operation(kind, params=None, column="x"):
    return {"kind": kind, "column": column, "params": params or {}}


@pytest.mark.parametrize("kind,values,params,expected", [
    ("trim", [" a ", "b", None], {}, ["a", "b", None]),
    ("normalize_missing", ["NA", "na", "", "null"], {"tokens": ["NA", ""]}, [None, "na", None, "null"]),
    ("case", ["aBC", "dEF", None], {"mode": "lower"}, ["abc", "def", None]),
    ("case", ["aBC", "dEF"], {"mode": "upper"}, ["ABC", "DEF"]),
    ("case", ["aBC test", "dEF"], {"mode": "title"}, ["Abc Test", "Def"]),
    ("map_categories", ["a", "b", "c", None], {"mapping": {"a": "b", "b": "c", "c": None}}, ["b", "c", None, None]),
    ("fill_missing", ["a", None, "b"], {"strategy": "constant", "value": ""}, ["a", "", "b"]),
    ("fill_missing", ["b", "a", None, "a", "b"], {"strategy": "mode"}, ["b", "a", "b", "a", "b"]),
])
def test_text_operations_no_mutation_and_parquet_roundtrip(kind, values, params, expected):
    df = frame({"x": pd.Series(values, dtype="string"), "other": range(len(values))})
    before = df.copy(deep=True)
    result = apply_operation(df, operation(kind, params))
    assert result["x"].fillna("<NULL>").tolist() == ["<NULL>" if value is None else value for value in expected]
    assert_frame_equal(df, before)
    assert result.index.tolist() == df.index.tolist()
    buffer = io.BytesIO()
    result.to_parquet(buffer)
    assert_frame_equal(result, pd.read_parquet(io.BytesIO(buffer.getvalue())))


@pytest.mark.parametrize("strategy,expected", [("mean", 4), ("median", 3), ("mode", 1)])
def test_numeric_imputation(strategy, expected):
    df = frame({"x": pd.Series([1, 3, 8, None], dtype="Int64")})
    before = df.copy(deep=True)
    result = apply_operation(df, operation("fill_missing", {"strategy": strategy}))
    assert result["x"].iloc[-1] == expected
    assert_frame_equal(df, before)


def test_fractional_imputation_promotes_integer_without_truncating():
    df = frame({"x": pd.Series([1, 2, None], dtype="Int64")})
    result = apply_operation(df, operation("fill_missing", {"strategy": "mean"}))
    assert result["x"].tolist() == [1, 2, 1.5]
    assert str(result["x"].dtype) == "Float64"


def test_numeric_conversion_is_strict_and_coercion_is_explicit():
    df = frame({"x": pd.Series(["001", "2.5", "bad", None], dtype="string")})
    with pytest.raises(ValueError):
        apply_operation(df, operation("to_numeric"))
    result = apply_operation(df, operation("to_numeric", {"coerce": True}))
    assert result["x"].iloc[0] == 1
    assert result["x"].iloc[1] == 2.5
    assert result["x"].isna().tolist() == [False, False, True, True]
    assert df["x"].iloc[0] == "001"


def test_large_integer_conversion_and_precision_guards():
    df = frame({"x": [str(2**63 + 1), str(2**63 + 2)]})
    result = apply_operation(df, operation("to_numeric"))
    assert result["x"].tolist() == [2**63 + 1, 2**63 + 2]
    assert str(result["x"].dtype) == "UInt64"
    with pytest.raises(ValueError, match="precision"):
        apply_operation(frame({"x": [str(2**53 + 1), "1.5"]}), operation("to_numeric"))
    with pytest.raises(ValueError, match="large integers"):
        apply_operation(frame({"x": pd.Series([2**53 + 1, None], dtype="Int64")}), operation("fill_missing", {"strategy": "mean"}))


def test_selected_numeric_corrections_and_nulls_before_strict_conversion():
    df = frame({"x": pd.Series(["1", "2.5", "two", "many", "-3", "0", None], dtype="string")})
    before = df.copy(deep=True)
    mapping = operation("map_categories", {"mapping": {"two": "2", "many": None}})
    preview = preview_operation(df, mapping)
    assert preview["changes"] == [{"row_id": 14, "column": "x", "before": "two", "after": "2"}, {"row_id": 16, "column": "x", "before": "many", "after": None}]
    assert_frame_equal(df, before)
    corrected = apply_operation(df, mapping)
    result = apply_operation(corrected, operation("to_numeric"))
    assert result["x"].dropna().tolist() == [1, 2.5, 2, -3, 0]
    assert profile(result)["column_profiles"][0]["numeric"]["finite_count"] == 5


def test_date_conversion_requires_exact_format_and_preserves_ids():
    df = frame({"x": ["31/01/2024", "bad", None]})
    with pytest.raises(ValueError):
        apply_operation(df, operation("to_date", {"format": "%d/%m/%Y"}))
    result = apply_operation(df, operation("to_date", {"format": "%d/%m/%Y", "coerce": True}))
    assert result["x"].iloc[0] == pd.Timestamp("2024-01-31")
    assert result["x"].isna().tolist() == [False, True, True]
    assert result.index.equals(df.index)
    with pytest.raises(ValueError):
        apply_operation(frame({"x": ["2024/01/01"]}), operation("to_date", {"format": "%Y-%m-%d"}))


def test_dates_with_offsets_have_parquet_compatible_single_timezone():
    df = frame({"x": ["2024-01-01T10:00:00+0200", "2024-01-01T10:00:00+0300"]})
    result = apply_operation(df, operation("to_date", {"format": "%Y-%m-%dT%H:%M:%S%z"}))
    assert str(result["x"].dtype) == "datetime64[ns, UTC]"
    buffer = io.BytesIO()
    result.to_parquet(buffer)
    assert_frame_equal(result, pd.read_parquet(io.BytesIO(buffer.getvalue())))


def test_supported_date_conversion_preview_and_ambiguity_guard():
    df = frame({"x": ["2026-09-04", "16/08/2026", "2026/10/02", "31-10-2026", "04/09/2026", None]})
    before = df.copy(deep=True)
    for coerce in (False, True):
        with pytest.raises(ValueError, match="Ambiguous"):
            preview_operation(df, operation("to_date", {"format": "supported", "coerce": coerce}))
    op = operation("to_date", {"format": "supported", "date_order": "day_first"})
    preview = preview_operation(df, op)
    assert preview["affected_cells"] == 5
    assert preview["changes"][4]["after"] == "2026-09-04T00:00:00+00:00"
    assert_frame_equal(df, before)
    result = apply_operation(df, op)
    assert result.index.equals(df.index)
    buffer = io.BytesIO()
    result.to_parquet(buffer)
    assert_frame_equal(result, pd.read_parquet(io.BytesIO(buffer.getvalue())))


def test_supported_date_invalid_policy_is_explicit():
    df = frame({"x": ["2026-13-04", "not-a-date", "2026/10/02"]})
    with pytest.raises(ValueError, match="invalid"):
        apply_operation(df, operation("to_date", {"format": "supported"}))
    result = apply_operation(df, operation("to_date", {"format": "supported", "coerce": True}))
    assert result["x"].isna().tolist() == [True, True, False]


def test_selected_duplicate_removal_only_and_stable_ids():
    df = frame({"x": ["a", "a", "a", "b"]})
    result = apply_operation(df, operation("drop_duplicates", {"row_ids": [14]}, None))
    assert result.index.tolist() == [10, 12, 16]
    assert result["x"].tolist() == ["a", "a", "b"]
    for ids in ([10], [16], [99]):
        with pytest.raises(ValueError):
            apply_operation(df, operation("drop_duplicates", {"row_ids": ids}, None))


def test_selected_outlier_clip_remove_and_infinity_handling():
    df = frame({"x": [0., 100., 200., np.inf, None]})
    clipped = apply_operation(df, operation("outliers", {"row_ids": [12], "action": "clip", "upper": 20}))
    assert clipped["x"].iloc[1] == 20 and clipped["x"].iloc[2] == 200
    removed = apply_operation(df, operation("outliers", {"row_ids": [12], "action": "remove"}))
    assert removed.index.tolist() == [10, 14, 16, 18]
    finite = apply_operation(df, operation("handle_infinity"))
    assert finite["x"].isna().tolist() == [False, False, False, True, True]
    assert np.isinf(df["x"].iloc[3])


def test_preview_diff_counts_removed_null_cells_and_columns():
    df = frame({"x": [" a ", "b", None], "y": [1, 2, 3]})
    before = df.copy(deep=True)
    result = preview_operation(df, operation("trim"))
    assert result["affected_cells"] == result["affected_rows"] == 1
    assert result["changes"] == [{"row_id": 10, "column": "x", "before": " a ", "after": "a"}]
    assert result["rows_removed"] == result["rows_added"] == 0
    dropped = preview_operation(df, operation("drop_column"))
    assert dropped["affected_cells"] == 3 and dropped["affected_rows"] == 3
    assert dropped["metrics_after"]["columns"] == 1
    assert len(dropped["changes"]) == 3
    assert_frame_equal(df, before)


def test_preview_counts_selected_duplicate_rows_with_nulls():
    df = frame({"x": ["a", "a"], "empty": [None, None]})
    result = preview_operation(df, operation("drop_duplicates", {"row_ids": [12]}, None))
    assert result["rows_removed"] == 1
    assert result["affected_cells"] == 2
    assert result["affected_rows"] == 1
    assert {change["column"] for change in result["changes"]} == {"x", "empty"}


def test_preview_bounded_changes_precise_totals_and_numeric_type_changes():
    df = frame({"x": ["1"] * 400})
    result = preview_operation(df, operation("to_numeric"))
    assert result["affected_cells"] == 400
    assert result["affected_rows"] == 400
    assert len(result["changes"]) == 200
    assert result["changes_truncated"] is True
    assert result["changes"][0] == {"row_id": 10, "column": "x", "before": "1", "after": 1}
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("op", [
    {}, {"kind": "unknown"}, {"kind": "trim", "column": "x", "extra": 1},
    operation("trim", {"extra": 1}), operation("trim", column="missing"),
    operation("normalize_missing"), operation("normalize_missing", {"tokens": [None]}),
    operation("drop_duplicates", column=None),
    operation("drop_duplicates", {"row_ids": []}, None),
    operation("drop_duplicates", {"row_ids": [True]}, None),
    operation("drop_duplicates", {"row_ids": [12, 12]}, None),
    operation("drop_duplicates", {"row_ids": [12]}, "x"),
    operation("to_numeric", {"coerce": "true"}),
    operation("to_date"), operation("to_date", {"format": "mixed"}),
    operation("fill_missing", {"strategy": "unknown"}),
    operation("fill_missing", {"strategy": "constant"}),
    operation("fill_missing", {"strategy": "constant", "value": np.inf}),
    operation("fill_missing", {"strategy": "mode", "value": "x"}),
    operation("case", {"mode": "casefold"}), operation("map_categories"),
    operation("map_categories", {"mapping": {"a": 1}}),
    operation("outliers", {"row_ids": [10], "action": "clip"}),
    operation("outliers", {"row_ids": [10], "action": "clip", "lower": 2, "upper": 1}),
    operation("outliers", {"row_ids": [10], "action": "clip", "lower": np.nan}),
    operation("outliers", {"row_ids": [10], "action": "remove", "upper": 1}),
    operation("outliers", {"row_ids": [10], "action": "unknown"}),
])
def test_invalid_operations_fail_without_mutating(op):
    df = frame({"x": ["a", "a"]})
    before = df.copy(deep=True)
    with pytest.raises(ValueError):
        apply_operation(df, op)
    assert_frame_equal(df, before)


@pytest.mark.parametrize("op", [operation("fill_missing", {"strategy": "mean"}), operation("handle_infinity"),
                                operation("outliers", {"row_ids": [10], "action": "clip", "upper": 5})])
def test_numeric_only_operations_reject_text(op):
    with pytest.raises(ValueError):
        apply_operation(frame({"x": ["text", None]}), op)


def test_imputation_cannot_invent_missing_mode_or_change_text_dtype():
    with pytest.raises(ValueError):
        apply_operation(frame({"x": [None, None]}), operation("fill_missing", {"strategy": "mode"}))
    with pytest.raises(ValueError):
        apply_operation(frame({"x": pd.Series(["a", None], dtype="string")}), operation("fill_missing", {"strategy": "constant", "value": 2}))


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r", "\n", "  =", "\u2003+"])
@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_export_escapes_headers_and_every_string_cell_without_mutation(prefix, format):
    dangerous = prefix + "formula-like text"
    df = frame({dangerous: [dangerous, "safe", "001"]})
    before = df.copy(deep=True)
    content, mimetype, extension = export_data(df, format)
    assert extension == format
    assert mimetype
    if format == "csv":
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    else:
        book = load_workbook(io.BytesIO(content), data_only=False)
        rows = list(book.active.values)
        assert all(cell.data_type != "f" for row in book.active for cell in row)
        book.close()
    assert rows[0][0] == "'" + dangerous
    assert rows[1][0] == "'" + dangerous
    assert rows[2][0] == "safe" and rows[3][0] == "001"
    assert all("__row_id__" not in str(row) for row in rows)
    assert_frame_equal(df, before)


def test_excel_preserves_large_integer_as_text_and_blank_strings():
    df = frame({"x": [2**63 + 1, 2**63 + 2], "text": ["", None]})
    content = export_data(df, "xlsx")[0]
    book = load_workbook(io.BytesIO(content), data_only=False)
    assert book.active["A2"].value == str(2**63 + 1)
    assert book.active["A2"].data_type == "s"
    assert book.active["B2"].value == ""
    assert book.active["B3"].value is None
    book.close()


@pytest.mark.parametrize("value", ["a" * 32768, "bad\x00text"])
def test_excel_refuses_truncation_or_illegal_xml(value):
    with pytest.raises(ValueError):
        export_data(frame({"x": [value]}), "xlsx")


def test_html_report_escapes_untrusted_values_and_json_is_finite():
    df = frame({'<script>test</script>': ["<img src=x>", None]})
    report = report_data(profile(df), quality(df), [{"operation": "</pre><script>test</script>"}], "html")[0].decode()
    assert "<script>" not in report and "<img src=x>" not in report
    assert "&lt;script&gt;" in report
    assert "Content-Security-Policy" in report
    content = report_data({"value": np.inf}, [], [], "json")[0]
    assert json.loads(content)["profile"]["value"] == "Infinity"


def test_generated_python_is_safe_deterministic_and_replays_exact_operations():
    operations = [operation("trim"), operation("map_categories", {"mapping": {"a": "quote'\\\nvalue"}})]
    code = generate_code(operations, "python")
    assert code == generate_code(operations, "python")
    tree = ast.parse(code)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"} for node in ast.walk(tree))
    # Read the embedded JSON as literals without executing generated reference code.
    assigned = next(node for node in tree.body if isinstance(node, ast.Assign) and node.targets[0].id == "OPERATIONS")
    embedded = json.loads(ast.literal_eval(assigned.value.args[0]))
    assert embedded == operations
    df = frame({"x": [" a ", "b"]})
    for op in embedded:
        df = apply_operation(df, op)
    assert df["x"].iloc[0] == "quote'\\\nvalue"
    assert "inspect_outliers" in code


def test_sql_escapes_identifiers_literals_and_marks_unsupported_conversions():
    column = 'odd"column; --'
    operations = [operation("map_categories", {"mapping": {"a'b\\c\n": "new"}}, column),
                  operation("to_numeric", column=column), operation("to_date", {"format": "%Y-%m-%d"}, column)]
    code = generate_code(operations, "sql")
    assert '"odd""column; --"' in code
    assert "E'a''b\\\\c\\n'" in code
    assert code.count("NOT TRANSLATED") == 2
    assert code.endswith("ROLLBACK;\n")
    assert code == generate_code(operations, "sql")


def test_sql_selected_rows_and_null_preserving_clip():
    code = generate_code([operation("outliers", {"row_ids": [12], "action": "clip", "lower": 0, "upper": 10})], "sql")
    assert 'WHERE "__row_id__" IN (12) AND "x" IS NOT NULL' in code


@pytest.mark.parametrize("call", [
    lambda: export_data(frame({"x": [1]}), "parquet"),
    lambda: report_data({}, [], [], "pdf"),
    lambda: generate_code([], "javascript"),
    lambda: generate_code([operation("trim", {"bad": 1})], "python"),
])
def test_unsupported_export_formats_and_operations(call):
    with pytest.raises(ValueError):
        call()
