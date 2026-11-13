"""Bounded CSV/XLSX readers. Unquoted blank CSV fields are structural nulls.

Explicitly quoted empty strings and all textual null tokens remain source strings.

Excel formulas are retained as literal formula text (never evaluated and no cached
value substitution). Mixed Excel scalar columns are represented as strings before
Parquet persistence; this is reported in DataFrame.attrs['warnings']. Dates are not
automatically parsed: the user must approve an explicit format conversion.
"""
from __future__ import annotations

import csv
import io
import math
import re
import warnings
import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

import pandas as pd
from charset_normalizer import from_bytes
from defusedxml import ElementTree as SafeET
from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

_DEFAULTS = {"max_upload_bytes": 25 * 1024**2, "max_rows": 100_000,
             "max_columns": 200, "max_uncompressed_bytes": 100 * 1024**2,
             "max_expansion_ratio": 100}
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z", re.ASCII)


def _limits(limits: dict) -> dict:
    if not isinstance(limits, dict):
        raise ValueError("Limits must be an object")
    result = {**_DEFAULTS, **limits}
    for key in _DEFAULTS:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid limit: {key}")
        if key != "max_expansion_ratio" and int(value) != value:
            raise ValueError(f"Limit must be an integer: {key}")
        if key != "max_expansion_ratio":
            result[key] = int(value)
    return result


def numeric_candidate(value: object, preserve_identifiers: bool = True) -> int | float | None:
    """Accept finite, losslessly representable decimal numbers only."""
    if isinstance(value, bool) or not isinstance(value, str) or not _NUMBER.fullmatch(value):
        return None
    unsigned = value.lstrip("+-")
    integer = re.split(r"[.eE]", unsigned)[0]
    if preserve_identifiers and len(integer) > 1 and integer.startswith("0"):
        return None
    try:
        decimal = Decimal(value)
        if not decimal.is_finite():
            return None
        if decimal == decimal.to_integral_value():
            if not -(2**63) <= decimal <= 2**64 - 1:
                return None
            return int(decimal)
        number = float(decimal)
        if not math.isfinite(number) or Decimal(str(number)) != decimal:
            return None
        return number
    except (ValueError, OverflowError, InvalidOperation):
        return None


def _numeric_series(series: pd.Series) -> pd.Series:
    present = series.dropna()
    if present.empty:
        return series.astype("string")
    values = [numeric_candidate(value) for value in present]
    if any(value is None for value in values):
        return series.astype("string")
    if all(isinstance(value, int) for value in values):
        minimum, maximum = min(values), max(values)
        if minimum < 0 and maximum >= 2**63:
            return series.astype("string")
        dtype = "UInt64" if maximum >= 2**63 else "Int64"
    else:
        if any(isinstance(value, int) and abs(value) > 2**53 for value in values):
            return series.astype("string")
        dtype = "Float64"
    parsed = iter(values)
    return pd.Series([pd.NA if pd.isna(v) else next(parsed) for v in series], index=series.index, dtype=dtype)


def _validate(data: bytes, filename: str, limits: dict) -> str:
    if not isinstance(data, bytes) or not data:
        raise ValueError("The uploaded file is empty")
    if len(data) > limits["max_upload_bytes"]:
        raise ValueError("Upload exceeds the configured byte limit")
    if not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename or any(ord(c) < 32 for c in filename):
        raise ValueError("Filename must be a plain filename without paths")
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in {".csv", ".xlsx"}:
        raise ValueError("Only CSV and XLSX files are supported")
    if extension == ".xlsx":
        _validate_zip(data, limits)
    elif data.startswith((b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"%PDF")):
        raise ValueError("The content is not CSV text")
    return extension[1:]


def _validate_zip(data: bytes, limits: dict) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [info.filename for info in entries]
            if len(entries) > 10_000 or len(set(names)) != len(names):
                raise ValueError("Invalid or excessive workbook ZIP entries")
            if not {"[Content_Types].xml", "xl/workbook.xml", "_rels/.rels"}.issubset(names):
                raise ValueError("ZIP archive is not an XLSX workbook")
            total = sum(info.file_size for info in entries)
            if total > limits["max_uncompressed_bytes"] or total / max(len(data), 1) > limits["max_expansion_ratio"]:
                raise ValueError("Workbook exceeds decompression limits")
            for info in entries:
                name = info.filename
                parts = PurePosixPath(name).parts
                if name.startswith("/") or ".." in parts or "\\" in name or ":" in name or info.flag_bits & 1:
                    raise ValueError("Unsafe workbook ZIP entry")
                if any(token in name.lower() for token in ("vbaproject", "externallinks/", "embeddings/", "activex/")):
                    raise ValueError("Active or external workbook content is unsupported")
                if info.file_size / max(info.compress_size, 1) > limits["max_expansion_ratio"]:
                    raise ValueError("Workbook entry exceeds expansion ratio")
                # Parse *all* XML, not just the worksheet selected by the user.
                if name.lower().endswith((".xml", ".rels")):
                    with archive.open(info) as stream:
                        row_count = 0
                        cells_in_row = 0
                        for event, element in SafeET.iterparse(stream, events=("start", "end")):
                            tag = element.tag.rsplit("}", 1)[-1]
                            if event == "start":
                                if tag == "row" and name.startswith("xl/worksheets/"):
                                    row_count += 1
                                    cells_in_row = 0
                                    if row_count > limits["max_rows"] + 1 or int(element.get("r", row_count)) > limits["max_rows"] + 1:
                                        raise ValueError("Workbook exceeds row limit")
                                if tag == "c" and name.startswith("xl/worksheets/"):
                                    cells_in_row += 1
                                    coordinate = element.get("r")
                                    if coordinate:
                                        letters, row = coordinate_from_string(coordinate)
                                        if column_index_from_string(letters) > limits["max_columns"] or row > limits["max_rows"] + 1:
                                            raise ValueError("Workbook exceeds row or column limit")
                                    if cells_in_row > limits["max_columns"]:
                                        raise ValueError("Workbook exceeds column limit")
                                if tag == "Relationship" and element.get("TargetMode", "").lower() == "external":
                                    raise ValueError("External workbook relationships are unsupported")
                                content = element.get("ContentType", "").lower()
                                if "macroenabled" in content or "vba" in content:
                                    raise ValueError("Macro-enabled content is unsupported")
                            else:
                                element.clear()
                else:
                    # CRC validation without extracting archive members to disk.
                    with archive.open(info) as stream:
                        while stream.read(64 * 1024):
                            pass
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid, unsafe, or corrupted XLSX workbook") from exc


def _decode(data: bytes, encoding: str | None) -> tuple[str, str]:
    if encoding is None:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16"
        else:
            try:
                data.decode("utf-8-sig")
                encoding = "utf-8-sig"
            except UnicodeDecodeError:
                match = from_bytes(data).best()
                if match is None or match.chaos > 0.1:
                    raise ValueError("Encoding is uncertain; select an explicit encoding")
                encoding = match.encoding
    try:
        text = data.decode(encoding)
    except (LookupError, UnicodeError, TypeError) as exc:
        raise ValueError("Unable to decode CSV with selected encoding") from exc
    if not text.strip() or any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise ValueError("CSV is empty or contains binary control characters")
    if text.lstrip().lower().startswith(("<!doctype html", "<html", "<?xml")):
        raise ValueError("The content is a document, not CSV")
    return text, encoding


def _quoted_record_fields(text: str, delimiter: str):
    """Track quoting metadata discarded by csv.reader, including multiline cells."""
    fields, quoted, in_quotes, field_start, record_started = [], False, False, True, False
    position = 0
    while position < len(text):
        char = text[position]
        if in_quotes:
            if char == '"':
                if position + 1 < len(text) and text[position + 1] == '"':
                    position += 1
                else:
                    in_quotes = False
        elif char == delimiter:
            fields.append(quoted)
            quoted, field_start, record_started = False, True, True
        elif char in "\r\n":
            if record_started:
                yield fields + [quoted]
            fields, quoted, field_start, record_started = [], False, True, False
            if char == "\r" and position + 1 < len(text) and text[position + 1] == "\n":
                position += 1
        else:
            if field_start and char == '"':
                quoted = in_quotes = True
            field_start, record_started = False, True
        position += 1
    if record_started:
        yield fields + [quoted]


def _csv_rows(data: bytes, options: dict, limits: dict) -> tuple[list[list], str, str, bool]:
    text, encoding = _decode(data, options.get("encoding"))
    delimiter = options.get("delimiter")
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n\x00"':
        raise ValueError("Delimiter must be one non-quote, non-newline character")
    rows = []
    quote_flags = iter(_quoted_record_fields(text, delimiter))
    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True):
            # Blank physical lines have no cells, unlike an explicitly empty field.
            if not row:
                continue
            if len(row) > limits["max_columns"]:
                raise ValueError("CSV exceeds column limit")
            quoted = next(quote_flags)
            if len(quoted) != len(row):
                raise ValueError("CSV quoting metadata is inconsistent")
            rows.append([None if value == "" and not is_quoted else value for value, is_quoted in zip(row, quoted)])
            if len(rows) > limits["max_rows"] + 1:
                raise ValueError("CSV exceeds row limit")
    except csv.Error as exc:
        raise ValueError("Malformed CSV or oversized field") from exc
    if not rows:
        raise ValueError("CSV has no records")
    try:
        has_header = csv.Sniffer().has_header(text[:65536])
    except csv.Error:
        has_header = True
    return rows, encoding, delimiter, has_header


def _excel_rows(data: bytes, options: dict, limits: dict) -> tuple[list[list], list[str], list[str]]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
        try:
            sheets = workbook.sheetnames
            if not sheets:
                raise ValueError("Workbook has no worksheets")
            sheet = options.get("sheet")
            if sheet is None:
                sheet = sheets[0]
            if not isinstance(sheet, str) or sheet not in sheets:
                raise ValueError("Unknown worksheet")
            worksheet = workbook[sheet]
            worksheet.reset_dimensions()
            rows = []
            notices = ["Excel formulas are preserved as literal text; cached values are not used.",
                       "Headers are normalized to unique strings; source __row_id__ is renamed to avoid the reserved index name."]
            for cells in worksheet.iter_rows():
                if len(cells) > limits["max_columns"]:
                    raise ValueError("Worksheet exceeds column limit")
                row = []
                for cell in cells:
                    value = cell.value
                    if getattr(cell, "data_type", None) == "f" and not isinstance(value, str):
                        raise ValueError("Unsupported array or data-table formula; export literal values first")
                    row.append(value)
                rows.append(row)
                if len(rows) > limits["max_rows"] + 1:
                    raise ValueError("Worksheet exceeds row limit")
            while rows and all(value is None for value in rows[-1]):
                rows.pop()
            if not rows:
                raise ValueError("Worksheet is empty")
            return rows, sheets, notices
        finally:
            workbook.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Unable to read XLSX workbook") from exc


def _labels(values: list) -> list[str]:
    result, used = [], {"__row_id__"}
    for position, value in enumerate(values, 1):
        base = str(value).strip() if value is not None else ""
        base = base or f"column_{position}"
        name, suffix = base, 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        result.append(name)
    return result


def _string_scalar(value: object) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    return str(value)


def _frame(rows: list[list], header: int | None, limits: dict, excel: bool) -> pd.DataFrame:
    if header is not None and (isinstance(header, bool) or not isinstance(header, int) or header < 0 or header >= len(rows)):
        raise ValueError("Header must be null or a valid zero-based row number")
    width = max(map(len, rows)) if excel else len(rows[header or 0])
    labels = _labels((rows[header] + [None] * width)[:width]) if header is not None else [f"column_{i + 1}" for i in range(width)]
    records = rows[header + 1:] if header is not None else rows
    if not records:
        raise ValueError("Dataset has a header but no data rows")
    if len(records) > limits["max_rows"] or width > limits["max_columns"]:
        raise ValueError("Dataset exceeds row or column limits")
    if not excel and any(len(row) != width for row in records):
        raise ValueError("Malformed CSV: inconsistent number of fields")
    records = [(row + [None] * width)[:width] for row in records]
    frame = pd.DataFrame(records, columns=labels, dtype=object)
    frame.index = pd.RangeIndex(len(frame), name="__row_id__")
    notices = []
    if header is not None and labels != [str(value) if value is not None else "" for value in rows[header]]:
        notices.append("Headers normalized to unique nonempty strings; __row_id__ is reserved for the stable internal index.")
    for column in labels:
        series = frame[column]
        present = series.dropna()
        kinds = {type(value) for value in present}
        if not kinds or all(isinstance(value, str) for value in present):
            frame[column] = _numeric_series(series)
        elif all(isinstance(value, bool) for value in present):
            frame[column] = series.astype("boolean")
        elif all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present):
            # Do not round large integer cells by implicitly mixing them with floats.
            converted = _numeric_series(series.map(lambda v: pd.NA if pd.isna(v) else str(v)))
            frame[column] = converted
            if str(converted.dtype) == "string":
                notices.append(f"Column {column!r}: numeric cells retained as lossless strings.")
        elif all(isinstance(value, datetime) and value.tzinfo is None for value in present):
            try:
                frame[column] = pd.to_datetime(series, errors="raise")
            except (ValueError, OverflowError):
                frame[column] = series.map(lambda v: pd.NA if pd.isna(v) else _string_scalar(v)).astype("string")
                notices.append(f"Column {column!r}: dates outside timestamp bounds retained as strings.")
        else:
            frame[column] = series.map(lambda v: pd.NA if pd.isna(v) else _string_scalar(v)).astype("string")
            notices.append(f"Column {column!r}: mixed Excel scalars explicitly represented as strings for Parquet; original scalar types remain in the source workbook.")
    frame.attrs["warnings"] = notices
    return frame


def inspect_file(data: bytes, filename: str, limits: dict) -> dict:
    limits = _limits(limits)
    file_format = _validate(data, filename, limits)
    if file_format == "csv":
        rows, encoding, delimiter, has_header = _csv_rows(data, {}, limits)
        return {"format": file_format, "sheets": [], "encoding": encoding,
                "delimiter": delimiter, "has_header": has_header, "preview": rows[:6],
                "warnings": ["Headers are normalized to unique strings; source __row_id__ is renamed to avoid the reserved index name.",
                             "Header and encoding detection are heuristic; confirm before ingestion.",
                             "Unquoted blank fields are null; quoted empty strings and textual null tokens are preserved. Dates require explicit conversion."]}
    rows, sheets, notices = _excel_rows(data, {}, limits)
    return {"format": file_format, "sheets": sheets, "encoding": None, "delimiter": None,
            "has_header": True, "preview": [[None if v is None else _string_scalar(v) for v in row] for row in rows[:6]],
            "warnings": notices}


def load_file(data: bytes, filename: str, options: dict, limits: dict) -> pd.DataFrame:
    if not isinstance(options, dict) or set(options) - {"sheet", "header", "delimiter", "encoding"}:
        raise ValueError("Unknown ingestion option")
    limits = _limits(limits)
    file_format = _validate(data, filename, limits)
    if file_format == "csv":
        if options.get("sheet") is not None:
            raise ValueError("CSV files do not have worksheets")
        rows, _, _, _ = _csv_rows(data, options, limits)
        notices = []
    else:
        if options.get("delimiter") is not None or options.get("encoding") is not None:
            raise ValueError("Encoding and delimiter options apply only to CSV")
        rows, _, notices = _excel_rows(data, options, limits)
    frame = _frame(rows, options.get("header", 0), limits, file_format == "xlsx")
    frame.attrs["warnings"].extend(notices)
    return frame
