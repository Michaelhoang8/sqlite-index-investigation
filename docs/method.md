# Method and data dictionary

## Data

`orders` is a single fact table with one row per fictional order. The main run has 200,000 rows. `data/sample_orders.csv` contains the first 250 generated rows for inspection; the complete database is regenerated from source.

| Column | SQLite type | Meaning |
|---|---|---|
| id | INTEGER PRIMARY KEY | Unique increasing order ID; rowid alias |
| customer_id | INTEGER NOT NULL | Fictional customer 1–5,000, uniformly sampled |
| created_at | TEXT NOT NULL | UTC ISO timestamp; three adjacent IDs deliberately share a timestamp |
| region | TEXT NOT NULL | Uniformly sampled North, South, East, West |
| status | TEXT NOT NULL | Seeded 83% paid / 8% open / 9% cancelled probability; realized counts in metadata |
| amount_cents | INTEGER NOT NULL | Positive fictional currency amount, 500–150,000 cents |
| note | TEXT NOT NULL | Synthetic payload to avoid benchmarking an unrealistically narrow table |

The note field is not returned by the benchmark queries. It makes table access materially different from a compact covering index. This choice influences index benefits and must be considered when generalizing results.

The three query definitions are in `src/investigation.py` and are exported as readable SQL files. The bound customer is 42; the bound region is North; the date cutoff is 30 days before the last generated timestamp. Index suites are alternative designs: do not execute all suites together against one database.

## Controls

The generator uses Python's deterministic `random.Random` with a recorded seed. A SHA-256 digest of the complete ordered rows is recorded in `results/environment.json`. Database files are copied before creating indexes so every suite starts with the same table content and layout.

Connections use `journal_mode=DELETE`, `synchronous=FULL`, a 32 MiB SQLite page-cache limit, in-memory temporary storage, and disabled automatic indexes. `ANALYZE` runs before warmups. Each suite is independently closed after measurement; the operating-system file cache is not flushed.

Three warmups precede 31 reads per query. Query order is shuffled within each repetition. The configuration order is seeded and recorded, but it is not counterbalanced over multiple runs. Timer resolution is Python's `perf_counter_ns`; displayed durations are milliseconds. Read results are fetched fully and checked against a reference outside the timing boundary. Exact ordered rows are compared, not just aggregate counts.

The p95 is a linearly interpolated sample quantile. Thirty-one local samples do not estimate a production service tail under load. No confidence interval or causal claim about small differences is implied.

## Storage and insertion

File bytes, SQLite page count and page size are recorded after index creation and statistics collection. Index build duration includes `ANALYZE`; the baseline also runs `ANALYZE`. These times are not pure index-build cost and are provided as supporting measurements rather than headline rankings.

Insertion trials add a 200-row batch in an existing transaction. The timer covers `executemany`; `BEGIN` and `ROLLBACK` are outside it. Every trial rolls back and the final table count is checked. This isolates index-maintenance work and Python/SQLite statement overhead; it deliberately does not claim durable write throughput, fsync cost or transaction scalability.

The covering/partial comparison retains the same customer and regional indexes and replaces only the queue index. Other adjacent suites alter three indexes at once. They answer a workload-level design question, not an isolated causal attribution for every index.

## Pagination

Both methods sort by the integer primary key and return the same projected columns. Offset scans past preceding rows; keyset is supplied the previous page's last ID. Cursor lookup is deliberately outside timing. Separate tests delete every seventh ID to ensure correctness does not rely on contiguous IDs. Timestamp ties exist in the data but pagination uses the unique ID, so ties cannot change page ordering.

## Next experiment

Run configurations in counterbalanced order across independent processes; vary selectivity and customer popularity; introduce simultaneous readers/writers; time committed batches under realistic durability; collect CPU and I/O profiles; and test realistic mixed query frequencies. Keep correctness checks for every changed access path. This repository provides a baseline for those experiments, not a production sizing result.
