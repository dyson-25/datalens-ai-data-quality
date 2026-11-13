"""Reproducible synthetic measurements; not production capacity guarantees."""
import io
import json
import resource
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from backend.analysis import anomalies, profile, quality
from backend.cleaning import apply_operation
from backend.config import Settings
from backend.exports import export_data
from backend.ingestion import load_file
from backend.main import create_app


def main():
    rng = np.random.default_rng(42)
    frame = pd.DataFrame({
        'name': [f' Person {i % 200} ' for i in range(2000)],
        'amount': rng.normal(100, 10, 2000),
        'quantity': rng.integers(1, 30, 2000),
        'region': ['North', 'South', 'East', 'West'] * 500,
        'constant': ['example'] * 2000,
    })
    frame.loc[0:19, 'amount'] = np.nan
    content = frame.to_csv(index=False).encode()
    measurements = {}

    def measure(name, operation):
        started = time.perf_counter()
        result = operation()
        measurements[name + '_seconds'] = round(time.perf_counter() - started, 6)
        return result

    with tempfile.TemporaryDirectory(prefix='datalens-benchmark-') as folder:
        settings = Settings(_env_file=None, app_env='test', storage_root=Path(folder), ai_enabled=False)
        with TestClient(create_app(settings)) as client:
            uploaded = measure('upload', lambda: client.post('/api/v1/datasets/upload', files={'file': ('benchmark.csv', content)}))
            assert uploaded.status_code == 201, uploaded.text
        parsed = measure('parsing', lambda: load_file(content, 'benchmark.csv', {'header': 0}, settings.limits))
        summary = measure('profiling', lambda: profile(parsed))
        findings = measure('quality_detection', lambda: quality(parsed))
        measure('anomaly_detection', lambda: anomalies(parsed, 'iqr', ['amount'], 1.5))
        cleaned = measure('cleaning', lambda: apply_operation(parsed, {'kind': 'trim', 'column': 'name', 'params': {}}))
        exported = measure('export', lambda: export_data(cleaned, 'csv'))
        restored = pd.read_csv(io.BytesIO(exported[0]))
        assert restored['name'].iloc[0] == 'Person 0'
        snapshot = Path(folder) / 'benchmark.parquet'
        parsed.to_parquet(snapshot)
        measurements['snapshot_bytes'] = snapshot.stat().st_size
    known = pd.DataFrame({'measurement': [1., 2., 3., 4., 100.]}, index=pd.Index(range(5), name='__row_id__'))
    algorithm_results = {}
    for method, threshold in [('iqr', 1.5), ('mad', 3.5)]:
        result = anomalies(known, method, ['measurement'], threshold)
        predicted = {row for finding in result['findings'] for row in finding['row_ids']}
        actual = {4}
        true_positive = len(predicted & actual)
        algorithm_results[method] = {
            'fixture': [1, 2, 3, 4, 100], 'expected_row_ids': [4], 'flagged_row_ids': sorted(predicted),
            'precision': true_positive / len(predicted) if predicted else 0,
            'recall': true_positive / len(actual),
        }
        assert predicted == actual, result
    assert summary['missing_cells'] == 20
    output = {'fixture': {'rows': len(frame), 'columns': len(frame.columns), 'csv_bytes': len(content), 'seed': 42},
              'measurements': measurements, 'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'planted_missing_cells': 20, 'observed_missing_cells': summary['missing_cells'],
              'quality_issue_groups': len(findings), 'anomaly_fixture_results': algorithm_results,
              'scope': 'One warm-process synthetic run, Linux peak RSS includes imports, not a concurrency or production capacity guarantee.'}
    print(json.dumps(output, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
