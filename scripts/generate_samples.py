"""Regenerate small, deterministic synthetic demonstrations without network access.

Run from the project root: .venv/bin/python scripts/generate_samples.py
All values are invented. XLSX serialization uses in-memory ZIP/XML, not temp files.
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.exports import export_data  # noqa: E402


def write_csv(path: Path, rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, quoting=csv.QUOTE_NOTNULL, lineterminator="\n")
        writer.writerows(rows)


def multi_sheet(clean: pd.DataFrame, messy: pd.DataFrame) -> bytes:
    first, second = export_data(clean, "xlsx")[0], export_data(messy, "xlsx")[0]
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(first)) as source, zipfile.ZipFile(io.BytesIO(second)) as other, zipfile.ZipFile(buffer, "w") as output:
        for name in source.namelist():
            content = source.read(name)
            if name == "xl/workbook.xml":
                content = content.replace(b'name="DataLens"', b'name="Clean reference"').replace(b"</sheets>", b'<sheet name="Quality issues" sheetId="2" r:id="rId2"/></sheets>')
            elif name == "xl/_rels/workbook.xml.rels":
                content = content.replace(b"</Relationships>", b'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
            elif name == "[Content_Types].xml":
                content = content.replace(b"</Types>", b'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, content)
        info = zipfile.ZipInfo("xl/worksheets/sheet2.xml", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        output.writestr(info, other.read("xl/worksheets/sheet1.xml"))
    return buffer.getvalue()


def main() -> None:
    root = Path.cwd()
    if root != Path(__file__).resolve().parents[1]:
        raise SystemExit("Run this script from the DataLens project root")
    target = root / "sample_datasets"
    target.mkdir(exist_ok=True)
    clean_rows = [["record_id", "region", "quantity", "amount", "order_date", "email", "phone"]]
    for i in range(1, 21):
        clean_rows.append([f"{i:05d}", ["North", "South", "East", "West"][(i - 1) % 4], i % 7 + 1,
                           round(10 + i * 2.5, 2), f"2024-01-{i:02d}", f"person{i}@example.test", f"+1202555{i:04d}"])
    messy_rows = [["record_id", "region", "amount", "quantity", "order_date", "email", "phone", "constant", "category_code", "category_code_copy"]]
    for i in range(1, 21):
        region = ["California", "California", "Californa", "california", " California "][i % 5]
        messy_rows.append([f"{i:05d}", region, float(i * 10), str(i), f"2024-01-{i:02d}",
                           f"person{i}@example.test", f"+1202555{i:04d}", "SYNTHETIC", f"AB-{i:03d}", f"AB-{i:03d}"])
    messy_rows[2][2] = None
    messy_rows[3][3] = "invalid"
    messy_rows[4][4] = "2024-02-30"
    messy_rows[5][4] = "31/01/2024"
    messy_rows[6][4] = "01/02/2024"
    messy_rows[7][5] = "not-an-email"
    messy_rows[8][6] = "123"
    messy_rows[9][2] = -30
    messy_rows[10][3] = "NA"
    messy_rows[11][1] = ""
    messy_rows[12][2] = 10000
    messy_rows[13][8] = messy_rows[13][9] = "AB/013"
    messy_rows.append(list(messy_rows[1]))
    write_csv(target / "clean_reference.csv", clean_rows)
    write_csv(target / "quality_issues.csv", messy_rows)
    rng = np.random.default_rng(42)
    anomaly_rows = [["observation", "height", "weight"]]
    for i, (height, weight) in enumerate(zip(rng.normal(170, 5, 100), rng.normal(70, 4, 100)), 1):
        anomaly_rows.append([f"obs-{i:03d}", round(float(height), 3), round(float(weight), 3)])
    anomaly_rows.extend([["obs-101", 250, 160], ["obs-102", None, 70]])
    write_csv(target / "statistical_anomalies.csv", anomaly_rows)
    clean = pd.DataFrame(clean_rows[1:], columns=clean_rows[0])
    messy = pd.DataFrame(messy_rows[1:], columns=messy_rows[0])
    (target / "multi_sheet.xlsx").write_bytes(multi_sheet(clean, messy))
    (target / "malformed.csv").write_bytes(b'a,b\n"unterminated,2\n')
    print("Generated clean_reference.csv, quality_issues.csv, statistical_anomalies.csv, multi_sheet.xlsx, malformed.csv")


if __name__ == "__main__":
    main()
