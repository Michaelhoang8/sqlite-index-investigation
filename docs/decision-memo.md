# Decision memo: access paths and their costs

## Result

The regional-sales median changes from **16.190 ms** with only the primary key to **1.128 ms** in the final suite (14.4× baseline/final ratio). The single-column suite measured **16.902 ms**: more indexes alone did not make that query faster.

The full covering suite occupies **46.26 MiB**. Replacing its queue index with an open-only partial index reduces this to **38.41 MiB**, saving **7.85 MiB** in this dataset. The customer and regional indexes are unchanged in that comparison. Insert-maintenance medians are **0.866 ms** for the baseline and **7.861 ms** for the final suite per 200 rows, excluding commit and rollback.

## Proposed design

For the three observed query patterns, retain ordered customer history and regional covering indexes. Use a partial queue index when the queue query keeps the exact `status = 'open'` predicate. Retain a full queue index instead if other statuses require the same access path. Do not extrapolate from the small timing difference between the covering and partial suites: the footprint reduction is direct, but their timing distributions and order effects need a larger experiment.

Use a last-seen primary-key cursor for sequential pagination. At a depth of 180,000 preceding rows, offset/keyset medians were 1.594/0.103 ms for identical 50-row results. Keyset requires a cursor and does not give arbitrary page-number access for free.

## Evidence and scope

- 200,000 seeded synthetic orders; 31 samples per query/configuration; 3 warmups.
- All index variants preserve exact result order, row count and checksum.
- Captured query plans show covering searches and the remaining temporary GROUP BY B-tree.
- Reads include `execute` and `fetchall`. Insertion measures statement/index work inside a transaction; rollback happens after timing.
- File sizes are measured after index creation and ANALYZE, before insertion trials.

## Limits and next experiment

This is one local, warmed-cache process with fixed query parameters and a seeded configuration order. It does not isolate disk throughput, durable commit cost, production p95, concurrency or network behavior. Identical indexes across the covering and partial suites can show different timings because of noise and cache/order effects. Run counterbalanced configurations across independent processes, skew customer popularity, vary time windows, and measure committed mixed read/write traffic before a production decision.

These are measured engineering observations over synthetic data, not real-business savings.
