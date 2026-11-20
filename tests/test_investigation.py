import csv
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from investigation import (INDEXES, QUERIES, OFFSET_SQL, KEYSET_SQL, INSERT_SQL,
                          apply_indexes, build_database, generate_orders, parameters,
                          percentile, query_plan)


class CorrectnessTests(unittest.TestCase):
    def test_generator_is_seeded_and_schema_is_valid(self):
        self.assertEqual(list(generate_orders(100)), list(generate_orders(100)))
        rows = list(generate_orders(100))
        self.assertEqual(len({r[0] for r in rows}), 100)
        self.assertTrue(all(r[5] > 0 for r in rows))
        self.assertEqual(rows[0][2], rows[1][2])  # Timestamp ties are deliberate.

    def test_all_index_suites_preserve_exact_results(self):
        reference = {}
        for suite in INDEXES:
            with self.subTest(suite=suite), tempfile.TemporaryDirectory() as folder:
                connection = build_database(Path(folder) / 'test.db', 3500)
                apply_indexes(connection, suite)
                for query, sql in QUERIES.items():
                    actual = connection.execute(sql, parameters(3500)[query]).fetchall()
                    if query in reference:
                        self.assertEqual(actual, reference[query])
                    reference[query] = actual
                connection.close()

    def test_keyset_matches_offset_even_when_ids_have_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            connection = build_database(Path(folder) / 'test.db', 1000)
            connection.execute('DELETE FROM orders WHERE id % 7 = 0')
            connection.commit()
            for depth in [0, 1, 49, 300, 850]:
                cursor = 0 if not depth else connection.execute(
                    'SELECT id FROM orders ORDER BY id LIMIT 1 OFFSET ?', (depth - 1,)).fetchone()[0]
                expected = connection.execute(OFFSET_SQL, (50, depth)).fetchall()
                actual = connection.execute(KEYSET_SQL, (cursor, 50)).fetchall()
                self.assertEqual(actual, expected)
            connection.close()

    def test_insert_measurement_can_restore_identical_state(self):
        with tempfile.TemporaryDirectory() as folder:
            connection = build_database(Path(folder) / 'test.db', 1000)
            apply_indexes(connection, 'partial')
            expected = connection.execute('SELECT COUNT(*), SUM(amount_cents) FROM orders').fetchone()
            connection.execute('BEGIN')
            connection.executemany(INSERT_SQL, generate_orders(200, start_id=1001))
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0], 1200)
            connection.rollback()
            self.assertEqual(connection.execute('SELECT COUNT(*), SUM(amount_cents) FROM orders').fetchone(), expected)
            connection.close()

    def test_partial_index_predicate_and_covering_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            connection = build_database(Path(folder) / 'test.db', 1000)
            apply_indexes(connection, 'partial')
            definition = connection.execute("SELECT sql FROM sqlite_master WHERE name='idx_open_queue'").fetchone()[0]
            self.assertIn("WHERE status = 'open'", definition)
            plan = ' '.join(query_plan(connection, QUERIES['customer_history'], (42,)))
            self.assertIn('COVERING INDEX idx_customer_history', plan)
            connection.close()

    def test_quantile_interpolation(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5], .5), 3)
        self.assertAlmostEqual(percentile([1, 2, 3, 4, 5], .95), 4.8)


class PublishedArtifactTests(unittest.TestCase):
    def test_all_published_results_reconcile_across_configurations(self):
        with (ROOT / 'results/result_checks.csv').open() as file:
            records = list(csv.DictReader(file))
        self.assertEqual(len(records), len(INDEXES) * len(QUERIES))
        for query in QUERIES:
            self.assertEqual(len({r['sha256'] for r in records if r['query'] == query}), 1)

    def test_recorded_summary_matches_raw_samples(self):
        with (ROOT / 'results/read_timings.csv').open() as file:
            raw = list(csv.DictReader(file))
        with (ROOT / 'results/read_summary.csv').open() as file:
            summary = list(csv.DictReader(file))
        metadata = json.loads((ROOT / 'results/environment.json').read_text())
        for entry in summary:
            values = [float(r['elapsed_ms']) for r in raw if r['configuration'] == entry['configuration'] and r['query'] == entry['query']]
            self.assertEqual(len(values), metadata['repetitions'])
            self.assertTrue(all(v > 0 for v in values))
            self.assertAlmostEqual(percentile(values, .5), float(entry['median_ms']))
            self.assertAlmostEqual(percentile(values, .95), float(entry['p95_ms']))


if __name__ == '__main__':
    unittest.main()
