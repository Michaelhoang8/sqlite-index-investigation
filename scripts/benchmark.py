"""Run actual local experiments. Timings are observations, not CI thresholds."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import random
import shutil
import sqlite3
import statistics
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from investigation import (INDEXES, QUERIES, SEED, OFFSET_SQL, KEYSET_SQL,
                          INSERT_SQL, build_database, connect, generate_orders,
                          parameters, apply_indexes, percentile, query_plan, result_digest)


def csv_write(path, rows):
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def timed_read(connection, sql, args):
    start = perf_counter_ns()
    output = connection.execute(sql, args).fetchall()
    return (perf_counter_ns() - start) / 1e6, output


def run(rows, repetitions, warmups, output):
    if rows < 1000 or repetitions < 5 or warmups < 1:
        raise ValueError('Use at least 1,000 rows, 5 repetitions and 1 warmup.')
    if not output.is_absolute():
        output = ROOT / output
    output.mkdir(parents=True, exist_ok=True)
    work = ROOT / '.work'
    work.mkdir(exist_ok=True)
    # Only known, generated files in this project's .work directory are replaced.
    base = work / 'source.sqlite3'
    if base.exists():
        base.unlink()
    connection = build_database(base, rows)
    checksum = result_digest(connection.execute('SELECT * FROM orders ORDER BY id').fetchall())
    distribution = dict(connection.execute('SELECT status, COUNT(*) FROM orders GROUP BY status'))
    sample = connection.execute('SELECT * FROM orders ORDER BY id LIMIT 250').fetchall()
    connection.close()
    (ROOT / 'data').mkdir(exist_ok=True)
    columns = ['id', 'customer_id', 'created_at', 'region', 'status', 'amount_cents', 'note']
    csv_write(ROOT / 'data/sample_orders.csv', [dict(zip(columns, row)) for row in sample])
    args = parameters(rows)
    read_rows, write_rows, storage_rows, plans, result_checks = [], [], [], [], []
    suite_order = list(INDEXES)
    random.Random(SEED).shuffle(suite_order)
    reference = {}
    for suite in suite_order:
        path = work / f'{suite}.sqlite3'
        shutil.copyfile(base, path)
        connection = connect(path)
        start = perf_counter_ns()
        apply_indexes(connection, suite)
        build_ms = (perf_counter_ns() - start) / 1e6
        storage_rows.append({'configuration': suite, 'bytes': path.stat().st_size,
                             'pages': connection.execute('PRAGMA page_count').fetchone()[0],
                             'page_size': connection.execute('PRAGMA page_size').fetchone()[0],
                             'index_build_and_analyze_ms': build_ms})
        for query, sql in QUERIES.items():
            actual = connection.execute(sql, args[query]).fetchall()
            if query in reference and actual != reference[query]:
                raise AssertionError(f'Result mismatch: {suite}/{query}')
            reference[query] = actual
            result_checks.append({'configuration': suite, 'query': query, 'row_count': len(actual),
                                  'sha256': result_digest(actual)})
            plans.append({'configuration': suite, 'query': query, 'parameters': args[query],
                          'plan': query_plan(connection, sql, args[query])})
            for _ in range(warmups):
                timed_read(connection, sql, args[query])
        order_rng = random.Random(SEED + suite_order.index(suite))
        for repetition in range(repetitions):
            order = list(QUERIES)
            order_rng.shuffle(order)
            for query in order:
                elapsed, actual = timed_read(connection, QUERIES[query], args[query])
                if actual != reference[query]:
                    raise AssertionError('Result changed during measurement')
                read_rows.append({'configuration': suite, 'query': query,
                                  'repetition': repetition + 1, 'elapsed_ms': elapsed,
                                  'result_rows': len(actual)})
        inserted = list(generate_orders(200, seed=SEED + 1, start_id=rows + 1))
        for repetition in range(-warmups, repetitions):
            connection.execute('BEGIN')
            start = perf_counter_ns()
            connection.executemany(INSERT_SQL, inserted)
            elapsed = (perf_counter_ns() - start) / 1e6
            connection.rollback()  # Excludes commit durability and preserves identical input state.
            if repetition >= 0:
                write_rows.append({'configuration': suite, 'repetition': repetition + 1,
                                   'batch_rows': 200, 'elapsed_ms': elapsed})
        if connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0] != rows:
            raise AssertionError('Insert benchmark failed to roll back')
        connection.close()
        print(f'{suite}: checked {len(QUERIES)} query outputs; measured {repetitions} repetitions', flush=True)

    page_rows, page_checks = [], []
    connection = connect(base)
    for depth in [0, rows // 4, rows // 2, (rows * 9) // 10]:
        # The cursor is obtained before timing. It represents a caller retaining
        # the last ID from the previous page, not arbitrary random page access.
        cursor = 0 if depth == 0 else connection.execute(
            'SELECT id FROM orders ORDER BY id LIMIT 1 OFFSET ?', (depth - 1,)).fetchone()[0]
        offset_args, keyset_args = (50, depth), (cursor, 50)
        offset_result = connection.execute(OFFSET_SQL, offset_args).fetchall()
        keyset_result = connection.execute(KEYSET_SQL, keyset_args).fetchall()
        if offset_result != keyset_result:
            raise AssertionError('Pagination results differ')
        page_checks.append({'offset': depth, 'cursor': cursor, 'row_count': len(offset_result),
                            'sha256': result_digest(offset_result),
                            'offset_plan': query_plan(connection, OFFSET_SQL, offset_args),
                            'keyset_plan': query_plan(connection, KEYSET_SQL, keyset_args)})
        methods = {'offset': (OFFSET_SQL, offset_args), 'keyset': (KEYSET_SQL, keyset_args)}
        for sql, params in methods.values():
            for _ in range(warmups):
                timed_read(connection, sql, params)
        for repetition in range(repetitions):
            for method in (['offset', 'keyset'] if repetition % 2 == 0 else ['keyset', 'offset']):
                elapsed, _ = timed_read(connection, *methods[method])
                page_rows.append({'method': method, 'offset': depth, 'repetition': repetition + 1,
                                  'elapsed_ms': elapsed, 'result_rows': len(offset_result)})
    connection.close()

    summary = []
    for suite in INDEXES:
        for query in QUERIES:
            values = [r['elapsed_ms'] for r in read_rows if r['configuration'] == suite and r['query'] == query]
            summary.append({'configuration': suite, 'query': query, 'n': len(values),
                            'median_ms': statistics.median(values), 'p95_ms': percentile(values, .95),
                            'min_ms': min(values), 'max_ms': max(values)})
    for name, records in [('read_timings.csv', read_rows), ('read_summary.csv', summary),
                          ('insert_timings.csv', write_rows), ('storage.csv', storage_rows),
                          ('pagination_timings.csv', page_rows), ('result_checks.csv', result_checks)]:
        csv_write(output / name, records)
    (output / 'query_plans.json').write_text(json.dumps(plans, indent=2) + '\n', encoding='utf-8')
    (output / 'pagination_checks.json').write_text(json.dumps(page_checks, indent=2) + '\n', encoding='utf-8')
    metadata = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
                'sqlite': sqlite3.sqlite_version, 'os': platform.system(), 'os_release': platform.release(),
                'architecture': platform.machine(), 'row_count': rows, 'seed': SEED,
                'repetitions': repetitions, 'warmups': warmups, 'configuration_order': suite_order,
                'data_sha256': checksum, 'status_counts': distribution,
                'cache_size_kib': 32768, 'journal_mode': 'DELETE', 'synchronous': 'FULL',
                'temp_store': 'MEMORY', 'automatic_index': False,
                'read_scope': 'execute plus fetchall; warmed connection and uncontrolled OS cache',
                'insert_scope': '200 inserts inside one transaction; begin and rollback excluded; no durable commit',
                'pagination_scope': '50 rows; keyset cursor supplied before timing; equivalent result sets',
                'limitations': ['Single local process; no concurrency', 'Configuration order seeded, not counterbalanced',
                                'Synthetic distribution and fixed query parameters', 'No cold-cache or disk-throughput claims',
                                'Sample p95 is descriptive, not a service-level estimate']}
    (output / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'sql').mkdir(exist_ok=True)
    for name, sql in QUERIES.items():
        (ROOT / f'sql/{name}.sql').write_text(sql + ';\n', encoding='utf-8')
    (ROOT / 'sql/index_suites.sql').write_text('-- ALTERNATIVE CONFIGURATIONS: do not execute this entire file.\n'
        '-- Each block is a separate design for a fresh database.\n'
        '-- Use scripts/benchmark.py or copy one block only; index names repeat.\n\n' + '\n\n'.join(
        '-- ' + name + '\n' + '\n'.join(sql + ';' for sql in statements)
        for name, statements in INDEXES.items()), encoding='utf-8')
    print(f'Saved measurements to {output.name}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, default=200000)
    parser.add_argument('--repetitions', type=int, default=31)
    parser.add_argument('--warmups', type=int, default=3)
    parser.add_argument('--output', type=Path, default=ROOT / 'results')
    options = parser.parse_args()
    run(options.rows, options.repetitions, options.warmups, options.output)
