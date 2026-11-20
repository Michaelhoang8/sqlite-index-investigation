"""Reproducible SQLite workload definitions; no third-party dependencies."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import random
import sqlite3

SEED = 81427
REGIONS = ('North', 'South', 'East', 'West')
EPOCH = datetime(2025, 1, 1)
SCHEMA = '''CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    region TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('paid','open','cancelled')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    note TEXT NOT NULL
)'''

# Every variant starts from an identical database. These are alternative index
# suites, not sequential mutations of the same cache or file.
INDEXES = {
    'baseline': [],
    'single_column': [
        'CREATE INDEX idx_customer ON orders(customer_id)',
        'CREATE INDEX idx_region ON orders(region)',
        'CREATE INDEX idx_status ON orders(status)',
    ],
    'composite': [
        'CREATE INDEX idx_customer_history ON orders(customer_id, created_at DESC, id DESC)',
        'CREATE INDEX idx_region_sales ON orders(region, status, created_at)',
        'CREATE INDEX idx_queue ON orders(status, created_at, id)',
    ],
    'covering': [
        'CREATE INDEX idx_customer_history ON orders(customer_id, created_at DESC, id DESC, status, amount_cents)',
        'CREATE INDEX idx_region_sales ON orders(region, status, created_at, amount_cents)',
        'CREATE INDEX idx_queue ON orders(status, created_at, id, customer_id, amount_cents)',
    ],
    'partial': [
        'CREATE INDEX idx_customer_history ON orders(customer_id, created_at DESC, id DESC, status, amount_cents)',
        'CREATE INDEX idx_region_sales ON orders(region, status, created_at, amount_cents)',
        "CREATE INDEX idx_open_queue ON orders(created_at, id, customer_id, amount_cents) WHERE status = 'open'",
    ],
}

QUERIES = {
    'customer_history': '''SELECT id, created_at, status, amount_cents
FROM orders
WHERE customer_id = ?
ORDER BY created_at DESC, id DESC
LIMIT 25''',
    'regional_sales': '''SELECT substr(created_at, 1, 10) AS order_day,
       COUNT(*) AS orders, SUM(amount_cents) AS revenue_cents
FROM orders
WHERE region = ? AND status = 'paid' AND created_at >= ?
GROUP BY substr(created_at, 1, 10)
ORDER BY order_day''',
    'open_queue': '''SELECT id, created_at, customer_id, amount_cents
FROM orders
WHERE status = 'open' AND created_at >= ?
ORDER BY created_at, id
LIMIT 100''',
}
OFFSET_SQL = 'SELECT id, created_at, amount_cents FROM orders ORDER BY id LIMIT ? OFFSET ?'
KEYSET_SQL = 'SELECT id, created_at, amount_cents FROM orders WHERE id > ? ORDER BY id LIMIT ?'
INSERT_SQL = 'INSERT INTO orders VALUES (?,?,?,?,?,?,?)'


def generate_orders(count: int, seed: int = SEED, start_id: int = 1):
    """Fictional UTC orders, one row per order; no real people or source data."""
    rng = random.Random(seed)
    for order_id in range(start_id, start_id + count):
        # Timestamp ties deliberately exercise deterministic pagination ordering.
        created = EPOCH + timedelta(minutes=((order_id - 1) // 3) * 5)
        yield (
            order_id,
            rng.randint(1, 5000),
            created.isoformat(timespec='seconds'),
            rng.choice(REGIONS),
            rng.choices(('paid', 'open', 'cancelled'), (83, 8, 9))[0],
            rng.randint(500, 150000),
            'synthetic-order-' + str(rng.randrange(10000)).zfill(4) + '-' + 'x' * 40,
        )


def connect(path):
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=DELETE')
    connection.execute('PRAGMA synchronous=FULL')
    connection.execute('PRAGMA cache_size=-32768')  # 32 MiB page cache per connection.
    connection.execute('PRAGMA temp_store=MEMORY')
    connection.execute('PRAGMA automatic_index=OFF')
    return connection


def build_database(path, rows: int):
    connection = connect(path)
    connection.execute(SCHEMA)
    connection.executemany(INSERT_SQL, generate_orders(rows))
    connection.commit()
    return connection


def apply_indexes(connection, name):
    for sql in INDEXES[name]:
        connection.execute(sql)
    connection.commit()
    connection.execute('ANALYZE')
    connection.commit()


def parameters(rows):
    final_time = EPOCH + timedelta(minutes=((rows - 1) // 3) * 5)
    cutoff = (final_time - timedelta(days=30)).isoformat(timespec='seconds')
    return {
        'customer_history': (42,),
        'regional_sales': ('North', cutoff),
        'open_queue': (cutoff,),
    }


def result_digest(rows):
    return hashlib.sha256(json.dumps(rows, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def query_plan(connection, sql, args):
    return [row[3] for row in connection.execute('EXPLAIN QUERY PLAN ' + sql, args)]


def percentile(values, q):
    """Linearly interpolated sample quantile, equivalent to NumPy's default."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
