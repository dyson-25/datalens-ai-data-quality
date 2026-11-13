import io
import zipfile

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from backend.exports import export_data
from backend.ingestion import inspect_file, load_file, numeric_candidate


LIMITS = {"max_upload_bytes": 2_000_000, "max_rows": 1000, "max_columns": 30,
          "max_uncompressed_bytes": 10_000_000, "max_expansion_ratio": 200}


def frame(values, columns=None):
    df = pd.DataFrame(values, columns=columns)
    df.index.name = "__row_id__"
    return df


def archive_replace(data, replacements, additions=None):
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            target.writestr(name, replacements.get(name, source.read(name)))
        for name, content in (additions or {}).items():
            target.writestr(name, content)
    return result.getvalue()


def workbook():
    return export_data(frame([[1, "Alice"], [2, "Bob"]], ["number", "name"]), "xlsx")[0]


@pytest.mark.parametrize("text,expected", [
    ("0", 0), ("-12", -12), ("1.25", 1.25), ("1e3", 1000), (".5", .5),
    ("001", None), ("-001", None), ("00.2", None), (" 1", None), ("1 ", None),
    ("NaN", None), ("inf", None), ("1e309", None), ("1,234", None),
    ("1.1234567890123456789", None), (str(2**64), None), ("1e-9999", None),
    ("１２", None), ("1_000", None), ("+2", 2), (str(2**64 - 1), 2**64 - 1),
])
def test_conservative_numeric_candidates(text, expected):
    assert numeric_candidate(text) == expected


def test_csv_preserves_tokens_identifiers_whitespace_and_exact_large_integers():
    raw = b'id,value,token,text\n001,9007199254740993,NA,  x \n002,9007199254740994,null,""\n003,9007199254740995,None,hello\n'
    df = load_file(raw, "input.csv", {}, LIMITS)
    assert df["id"].tolist() == ["001", "002", "003"]
    assert df["value"].tolist() == [9007199254740993, 9007199254740994, 9007199254740995]
    assert df["token"].tolist() == ["NA", "null", "None"]
    assert df["text"].tolist() == ["  x ", "", "hello"]
    assert df.index.name == "__row_id__"
    assert df.isna().sum().sum() == 0
    result = io.BytesIO()
    df.to_parquet(result)
    assert_frame_equal(df, pd.read_parquet(io.BytesIO(result.getvalue())))


def test_csv_quoted_empty_strings_are_not_coerced_during_numeric_inference():
    df = load_file(b'number,date\n1,2024-01-01\n"",2024-01-02\n3,2024-01-03\n', "x.csv", {}, LIMITS)
    assert df["number"].tolist() == ["1", "", "3"]
    assert str(df["date"].dtype) == "string"


@pytest.mark.parametrize("raw,options,expected", [
    (b"a;b\n1;2\n", {}, ["a", "b"]),
    (b"a\tb\n1\t2\n", {}, ["a", "b"]),
    (b"meta\na,b\n1,2\n", {"header": 1, "delimiter": ","}, ["a", "b"]),
    (b"a,b\n1,2\n", {"header": None}, ["column_1", "column_2"]),
    (b"a,a,a_2,,__row_id__\n1,2,3,4,5\n", {}, ["a", "a_2", "a_2_2", "column_4", "__row_id___2"]),
])
def test_headers_and_delimiters(raw, options, expected):
    df = load_file(raw, "DATA.CSV", options, LIMITS)
    assert list(df.columns) == expected
    assert len(set(df.columns)) == len(df.columns)
    buffer = io.BytesIO()
    df.to_parquet(buffer)
    assert_frame_equal(df, pd.read_parquet(io.BytesIO(buffer.getvalue())))


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "cp1252"])
def test_encodings(encoding):
    data = "city,value\nMontréal,1\n".encode(encoding)
    options = {"encoding": encoding} if encoding == "cp1252" else {}
    assert load_file(data, "x.csv", options, LIMITS).iloc[0, 0] == "Montréal"


def test_quoted_newlines_are_preserved():
    df = load_file(b'name,note\nAlice,"line one\nline two"\n', "x.csv", {}, LIMITS)
    assert df.iloc[0, 1] == "line one\nline two"


@pytest.mark.parametrize("raw,name,options,limits", [
    (b"", "x.csv", {}, {}), (b"   ", "x.csv", {}, {}),
    (b"a\n1", "../x.csv", {}, {}), (b"a\n1", "folder\\x.csv", {}, {}),
    (b"a\n1", "x.xls", {}, {}), (b"a\n1", "x.xlsm", {}, {}),
    (b"a\n1", "x.xlsx", {}, {}), (b"%PDF-1.7", "x.csv", {}, {}),
    (b"a\x00b\n1", "x.csv", {}, {}),
    (b"<html>content</html>", "x.csv", {}, {}),
    (b'a,b\n"unterminated,2', "x.csv", {}, {}),
    (b"a,b\n1,2,3\n", "x.csv", {"delimiter": ","}, {}),
    (b"a\n", "x.csv", {}, {}),
    (b"a\n1", "x.csv", {"header": -1}, {}),
    (b"a\n1", "x.csv", {"header": True}, {}),
    (b"a\n1", "x.csv", {"header": 100}, {}),
    (b"a\n1", "x.csv", {"delimiter": "::"}, {}),
    (b"a\n1", "x.csv", {"encoding": "unknown-codec"}, {}),
    (b"a\n1", "x.csv", {"sheet": "Sheet1"}, {}),
    (b"a\n1", "x.csv", {"unexpected": True}, {}),
    (b"a\n1", "x.csv", {}, {"max_upload_bytes": 1}),
    (b"a\n1\n2\n", "x.csv", {}, {"max_rows": 1}),
    (b"a,b\n1,2", "x.csv", {}, {"max_columns": 1}),
    (b"a\n1", "x.csv", {}, {"max_rows": float("nan")}),
    (b"a\n1", "x.csv", {}, {"max_columns": 0}),
])
def test_ingestion_rejects_invalid_inputs(raw, name, options, limits):
    with pytest.raises(ValueError):
        load_file(raw, name, options, {**LIMITS, **limits})


def test_no_header_limit_counts_every_row():
    with pytest.raises(ValueError, match="limits"):
        load_file(b"a\nb\n", "x.csv", {"header": None}, {**LIMITS, "max_rows": 1})


def test_inspection_does_not_change_source():
    raw = b"a,b\n1,2\n"
    result = inspect_file(raw, "x.csv", LIMITS)
    assert result["format"] == "csv"
    assert result["preview"] == [["a", "b"], ["1", "2"]]
    assert result["delimiter"] == ","
    assert "reserved" in " ".join(result["warnings"])
    assert raw == b"a,b\n1,2\n"


def test_excel_roundtrip_and_sheets():
    raw = workbook()
    inspected = inspect_file(raw, "x.xlsx", LIMITS)
    assert inspected["sheets"] == ["DataLens"]
    df = load_file(raw, "x.xlsx", {"sheet": "DataLens"}, LIMITS)
    assert df["number"].tolist() == [1, 2]
    assert df["name"].tolist() == ["Alice", "Bob"]
    with pytest.raises(ValueError, match="worksheet"):
        load_file(raw, "x.xlsx", {"sheet": "missing"}, LIMITS)
    for option in ({"encoding": "utf8"}, {"delimiter": ","}):
        with pytest.raises(ValueError):
            load_file(raw, "x.xlsx", option, LIMITS)


def test_excel_formula_preserved_even_without_cache_and_mixed_types_parquet():
    xml = '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" t="inlineStr"><is><t>mixed</t></is></c><c r="B1" t="inlineStr"><is><t>formula</t></is></c></row>
<row r="2"><c r="A2" t="b"><v>1</v></c><c r="B2"><f>SUM(1,2)</f></c></row>
<row r="3"><c r="A3" t="n"><v>2</v></c><c r="B3" t="inlineStr"><is><t>literal</t></is></c></row>
<row r="4"><c r="A4" t="d"><v>2024-01-01T12:00:00</v></c></row>
</sheetData></worksheet>'''
    df = load_file(archive_replace(workbook(), {"xl/worksheets/sheet1.xml": xml}), "x.xlsx", {}, LIMITS)
    assert df["mixed"].tolist() == ["True", "2", "2024-01-01T12:00:00"]
    assert df["formula"].iloc[0] == "=SUM(1,2)"
    assert pd.isna(df["formula"].iloc[2])
    assert any("mixed Excel" in text for text in df.attrs["warnings"])
    buffer = io.BytesIO()
    df.to_parquet(buffer)
    assert_frame_equal(df, pd.read_parquet(io.BytesIO(buffer.getvalue())))


def test_multi_sheet_selection():
    raw = workbook()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").replace(b"Alice", b"Other")
        book = archive.read("xl/workbook.xml").replace(b"</sheets>", b'<sheet name="Second" sheetId="2" r:id="rId2"/></sheets>')
        rels = archive.read("xl/_rels/workbook.xml.rels").replace(b"</Relationships>", b'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
        types = archive.read("[Content_Types].xml").replace(b"</Types>", b'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    raw = archive_replace(raw, {"xl/workbook.xml": book, "xl/_rels/workbook.xml.rels": rels, "[Content_Types].xml": types}, {"xl/worksheets/sheet2.xml": sheet})
    assert inspect_file(raw, "multi.xlsx", LIMITS)["sheets"] == ["DataLens", "Second"]
    assert load_file(raw, "multi.xlsx", {"sheet": "Second"}, LIMITS).iloc[0, 1] == "Other"


@pytest.mark.parametrize("addition", [
    {"../escape.xml": "<a/>"}, {"/absolute.xml": "<a/>"},
    {"xl/vbaProject.bin": b"macro marker"}, {"xl/embeddings/object.bin": b"object marker"},
    {"xl/extra.xml": '<!DOCTYPE a [<!ENTITY x "test">]><a>&x;</a>'},
    {"xl/extra.xml": "<unclosed>"},
    {"xl/extra.rels": '<Relationships><Relationship TargetMode="External" Target="https://example.invalid"/></Relationships>'},
])
def test_unsafe_workbook_members_rejected(addition):
    with pytest.raises(ValueError):
        inspect_file(archive_replace(workbook(), {}, addition), "x.xlsx", LIMITS)


@pytest.mark.parametrize("limit", [
    {"max_uncompressed_bytes": 100}, {"max_expansion_ratio": 1},
    {"max_columns": 1}, {"max_rows": 1},
])
def test_workbook_limits(limit):
    with pytest.raises(ValueError):
        load_file(workbook(), "x.xlsx", {}, {**LIMITS, **limit})


def test_worksheet_reported_dimensions_cannot_hide_cells():
    raw = workbook()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").replace(b"<sheetData>", b'<dimension ref="A1:A1"/><sheetData>')
    df = load_file(archive_replace(raw, {"xl/worksheets/sheet1.xml": sheet}), "x.xlsx", {}, LIMITS)
    assert df.shape == (2, 2)


def test_sparse_huge_coordinate_is_rejected_before_loading():
    xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="XFD1048576" t="n"><v>1</v></c></row></sheetData></worksheet>'
    with pytest.raises(ValueError, match="limit"):
        load_file(archive_replace(workbook(), {"xl/worksheets/sheet1.xml": xml}), "x.xlsx", {}, LIMITS)


def test_actual_zip_disguised_as_csv():
    with pytest.raises(ValueError, match="CSV"):
        inspect_file(workbook(), "x.csv", LIMITS)
