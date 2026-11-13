"""In-memory, escaped exports and deterministic, never-executed reference code.

XLSX uses inline text cells, not formulas. Strings/headers beginning with spreadsheet
formula prefixes are additionally apostrophe-escaped in both CSV and XLSX. Excel
cannot faithfully store >15 significant numeric digits, so these are text cells;
dates are ISO text to avoid spreadsheet timezone/epoch loss. Source frames remain
unchanged. PostgreSQL snippets are reference-only and require schema adaptation.
"""
from __future__ import annotations

import csv
import html
import io
import json
import math
import re
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
from openpyxl.utils.cell import get_column_letter

from .analysis import json_safe
from .cleaning import validate_operation

_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _spreadsheet_safe(value):
    if isinstance(value, str):
        stripped = re.sub(r"^[\s\x00-\x1f\ufeff\u200b\u200c\u200d]+", "", value)
        if value.startswith(("\t", "\r", "\n")) or stripped.startswith(("=", "+", "-", "@")):
            return "'" + value
        return value
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.floating, float)) and not math.isfinite(value):
        return None if math.isnan(value) else ("Infinity" if value > 0 else "'-Infinity")
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _xlsx_text(value: str) -> str:
    if len(value) > 32767:
        raise ValueError("Excel text cells cannot exceed 32,767 characters; use CSV instead")
    if _XML_INVALID.search(value):
        raise ValueError("A cell contains characters not supported by XML/XLSX; use CSV instead")
    return escape(value).replace("\r", "&#13;")


def _xlsx_cell(value, coordinate: str) -> str:
    if value is None:
        return f'<c r="{coordinate}"/>'
    if isinstance(value, bool):
        return f'<c r="{coordinate}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)):
        text = str(value)
        significant = len(re.sub(r"[^0-9]", "", text.split("e")[0].lstrip("-+0").rstrip("0")))
        if isinstance(value, int):
            significant = len(str(abs(value)))
        if significant <= 15 and math.isfinite(value):
            return f'<c r="{coordinate}" t="n"><v>{text}</v></c>'
        value = text
    text = _xlsx_text(str(value))
    return f'<c r="{coordinate}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _zip_entry(name: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    return entry


def export_data(df: pd.DataFrame, format: str) -> tuple[bytes, str, str]:
    if format not in {"csv", "xlsx"}:
        raise ValueError("Export format must be csv or xlsx")
    headers = [_spreadsheet_safe(str(name)) for name in df.columns]
    if format == "csv":
        stream = io.StringIO(newline="")
        # Python 3.12 QUOTE_NOTNULL preserves null versus explicitly empty text.
        writer = csv.writer(stream, lineterminator="\r\n", quoting=csv.QUOTE_NOTNULL)
        writer.writerow(headers)
        for row in df.itertuples(index=False, name=None):
            writer.writerow([_spreadsheet_safe(value) for value in row])
        return stream.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", "csv"
    if len(df) > 1_048_575 or len(df.columns) > 16_384:
        raise ValueError("Dataset exceeds XLSX worksheet dimensions")
    stream = io.BytesIO()
    # Write XML directly to a ZIP buffer: openpyxl's writer uses temporary files.
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_zip_entry("[Content_Types].xml"), '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr(_zip_entry("_rels/.rels"), '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr(_zip_entry("xl/workbook.xml"), '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="DataLens" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr(_zip_entry("xl/_rels/workbook.xml.rels"), '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        with archive.open(_zip_entry("xl/worksheets/sheet1.xml"), "w") as sheet:
            sheet.write(b'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
            def write_row(number, values):
                cells = [_xlsx_cell(value, f"{get_column_letter(i)}{number}") for i, value in enumerate(values, 1)]
                sheet.write((f'<row r="{number}">' + "".join(cells) + "</row>").encode("utf-8"))
            write_row(1, headers)
            for number, row in enumerate(df.itertuples(index=False, name=None), 2):
                write_row(number, [_spreadsheet_safe(value) for value in row])
            sheet.write(b"</sheetData></worksheet>")
    return stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"


def report_data(profile: dict, issues: list, history: dict | list, format: str) -> tuple[bytes, str, str]:
    if format not in {"json", "html"}:
        raise ValueError("Report format must be json or html")
    payload = json_safe({"profile": profile, "issues": issues, "history": history,
                         "notice": "Deterministic findings describe the active snapshot. Heuristic findings and statistical outliers are not confirmed errors. Export escaping may add apostrophes; the source dataset is unchanged."})
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
    if format == "json":
        return serialized.encode("utf-8"), "application/json", "json"
    sections = []
    for key, value in payload.items():
        content = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
        sections.append(f"<section><h2>{html.escape(key.title())}</h2><pre>{html.escape(content)}</pre></section>")
    document = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>DataLens quality report</title><style>body{font:16px system-ui;margin:2rem;color:#172033}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5fa;padding:1rem}h1,h2{color:#175f65}@media print{pre{background:white}section{break-inside:auto}}</style></head><body><h1>DataLens quality report</h1>' + "".join(sections) + "</body></html>"
    return document.encode("utf-8"), "text/html; charset=utf-8", "html"


def _identifier(value: str) -> str:
    if "\x00" in value:
        raise ValueError("PostgreSQL identifiers cannot contain NUL")
    return '"' + value.replace('"', '""') + '"'


def _literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("SQL reference values must be finite")
        return str(value)
    if "\x00" in str(value):
        raise ValueError("PostgreSQL text values cannot contain NUL")
    # Explicit E literals remain safe independently of standard_conforming_strings.
    return "E'" + str(value).replace("\\", "\\\\").replace("'", "''").replace("\n", "\\n").replace("\r", "\\r") + "'"


def generate_code(operations: list[dict], language: str) -> str:
    if language not in {"python", "sql"}:
        raise ValueError("Reference language must be python or sql")
    if not isinstance(operations, list):
        raise ValueError("Operations must be a list")
    validated = [validate_operation(operation) for operation in operations]
    if language == "python":
        serialized = json.dumps(operations, ensure_ascii=True, allow_nan=False, sort_keys=True)
        return ("# DataLens deterministic reference pipeline; review before running.\n"
                "# Requires this DataLens checkout and its pinned environment.\n"
                "# Load the baseline with backend.ingestion.load_file to retain stable row IDs.\n"
                "# Never reset/recreate row IDs after filtering. Source files are not overwritten.\n"
                "import json\n"
                "from backend.cleaning import apply_operation\n"
                "from backend.analysis import anomalies\n\n"
                f"OPERATIONS = json.loads({serialized!r})\n\n"
                "def replay(baseline):\n"
                "    cleaned = baseline.copy(deep=True)\n"
                "    for operation in OPERATIONS:\n"
                "        cleaned = apply_operation(cleaned, operation)\n"
                "    return cleaned\n\n"
                "def inspect_outliers(frame, columns):\n"
                "    # Inspection only: no automatic deletions.\n"
                "    return {\n"
                "        'iqr': anomalies(frame, 'iqr', columns, threshold=1.5),\n"
                "        'mad': anomalies(frame, 'mad', columns, threshold=3.5),\n"
                "    }\n")
    lines = ["-- PostgreSQL reference only; never executed by DataLens.",
             "-- Adapt table names/types to your schema and review every statement.",
             '-- Work on a private COPY named "datalens_work", not the source table.',
             '-- "__row_id__" must hold the stable DataLens baseline IDs (not row_number()).',
             "-- SQL NULL differs from empty text. Case/collation, whitespace and date parsing",
             "-- can differ from Python. Unsupported exact translations are explicitly skipped.",
             "BEGIN;"]
    table, row_id = '"datalens_work"', '"__row_id__"'
    for number, (kind, column, params) in enumerate(validated, 1):
        lines.append(f"\n-- Step {number}: {kind}")
        col = _identifier(column) if column is not None else None
        if kind == "trim":
            lines.append("-- btrim handles ASCII whitespace; Python str.strip also handles Unicode whitespace.")
            lines.append(f"UPDATE {table} SET {col} = btrim({col}, E' \\t\\n\\r\\f\\v');")
        elif kind == "normalize_missing":
            tokens = ", ".join(_literal(value) for value in params["tokens"])
            lines.append(f"UPDATE {table} SET {col} = NULL WHERE {col} IN ({tokens});")
        elif kind == "drop_duplicates":
            lines.append("-- Preconditions: selected IDs were reviewed as non-first exact duplicates in this version.")
            ids = ", ".join(str(value) for value in params["row_ids"])
            lines.append(f"DELETE FROM {table} WHERE {row_id} IN ({ids});")
        elif kind in {"to_numeric", "to_date"}:
            lines.append("-- NOT TRANSLATED: PostgreSQL casts/date parsers do not reproduce DataLens")
            lines.append("-- strict finite/precision/date-format validation and explicit coercion exactly.")
            lines.append("-- Use the generated Python pipeline, or add a reviewed schema-specific staging conversion.")
        elif kind == "fill_missing":
            strategy = params["strategy"]
            if strategy == "constant":
                value = _literal(params["value"])
            elif strategy in {"mean", "median"}:
                aggregate = f"avg({col})" if strategy == "mean" else f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {col})"
                value = f"(SELECT {aggregate} FROM {table} WHERE {col} IS NOT NULL AND {col}::text NOT IN ('Infinity', '-Infinity', 'NaN'))"
                lines.append("-- Ensure the target numeric type represents fractional results without rounding.")
            else:
                value = f"(SELECT {col} FROM {table} WHERE {col} IS NOT NULL GROUP BY {col} ORDER BY count(*) DESC, min({row_id}) ASC LIMIT 1)"
                lines.append("-- Mode ties follow the first stable row ID (requires baseline row order).")
            lines.append(f"UPDATE {table} SET {col} = {value} WHERE {col} IS NULL;")
        elif kind == "drop_column":
            lines.append(f"ALTER TABLE {table} DROP COLUMN {col};")
        elif kind == "case":
            function = {"lower": "lower", "upper": "upper", "title": "initcap"}[params["mode"]]
            lines.append("-- Locale/Unicode casing and initcap differ from Python in some languages.")
            lines.append(f"UPDATE {table} SET {col} = {function}({col});")
        elif kind == "map_categories":
            clauses = " ".join(f"WHEN {_literal(key)} THEN {_literal(value)}" for key, value in params["mapping"].items())
            lines.append(f"UPDATE {table} SET {col} = CASE {col} {clauses} ELSE {col} END;")
        elif kind == "handle_infinity":
            lines.append(f"UPDATE {table} SET {col} = NULL WHERE {col}::text IN ('Infinity', '-Infinity');")
        elif kind == "outliers":
            ids = ", ".join(str(value) for value in params["row_ids"])
            if params["action"] == "remove":
                lines.append(f"DELETE FROM {table} WHERE {row_id} IN ({ids});")
            else:
                expression = col
                if params.get("lower") is not None:
                    expression = f"greatest({expression}, {_literal(params['lower'])})"
                if params.get("upper") is not None:
                    expression = f"least({expression}, {_literal(params['upper'])})"
                lines.append(f"UPDATE {table} SET {col} = {expression} WHERE {row_id} IN ({ids}) AND {col} IS NOT NULL;")
    lines.extend(["", "-- Inspect results in your SQL client; replace ROLLBACK with COMMIT only after approval.", "ROLLBACK;", ""])
    return "\n".join(lines)
