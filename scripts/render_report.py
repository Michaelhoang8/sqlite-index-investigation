"""Render the committed measurements; does not run or simulate benchmarks."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path
import statistics
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from investigation import INDEXES, QUERIES


def read_csv(name):
    with (ROOT / 'results' / name).open(encoding='utf-8') as file:
        return list(csv.DictReader(file))


def render():
    output = ROOT / 'docs/charts'
    output.mkdir(parents=True, exist_ok=True)
    summaries = read_csv('read_summary.csv')
    raw = read_csv('read_timings.csv')
    writes = read_csv('insert_timings.csv')
    storage = read_csv('storage.csv')
    pagination = read_csv('pagination_timings.csv')
    metadata = json.loads((ROOT / 'results/environment.json').read_text())
    plans = json.loads((ROOT / 'results/query_plans.json').read_text())
    names = list(INDEXES)
    labels = ['Primary key only', 'Single-column', 'Composite', 'Covering', 'Partial queue']
    colors = ['#aab7c9', '#91aed2', '#5b85b5', '#244a76', '#2865b3']
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'figure.facecolor': '#f1f5fa', 'axes.facecolor': '#f1f5fa',
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.spines.left': False, 'axes.edgecolor': '#cbd7e4',
                         'axes.labelcolor': '#3b526e', 'xtick.color': '#3b526e',
                         'ytick.color': '#3b526e', 'savefig.dpi': 160})

    def export(fig, name):
        fig.text(.01, .012, f"Measured local SQLite workload · {metadata['row_count']:,} synthetic rows · {metadata['repetitions']} repeats", fontsize=8, color='#64768c')
        fig.savefig(output / f'{name}.png', bbox_inches='tight')
        fig.savefig(output / f'{name}.svg', bbox_inches='tight')
        plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(14, 5.5))
    for ax, query in zip(axes, QUERIES):
        entries = [next(r for r in summaries if r['configuration'] == name and r['query'] == query) for name in names]
        values = [float(r['median_ms']) for r in entries]
        ax.barh(labels, values, color=colors, height=.58)
        ax.invert_yaxis()
        ax.set_xscale('log')
        ax.set_xlim(.02, max(values) * 3)
        ax.set_title(query.replace('_', ' ').title(), loc='left', fontweight='bold', pad=18)
        ax.set_xlabel('Median latency, ms · log scale')
        for i, value in enumerate(values):
            ax.text(value * 1.1, i, f'{value:.3f}', va='center', fontsize=9)
        ax.grid(axis='x', alpha=.15)
        ax.set_axisbelow(True)
    fig.suptitle('Read cost depends on the access path', x=.01, ha='left', fontsize=21, fontweight='bold')
    fig.tight_layout(rect=(0, .06, 1, .93))
    export(fig, '01_read_latency')

    sizes = [int(next(r for r in storage if r['configuration'] == name)['bytes']) / 2**20 for name in names]
    insert_ms = [statistics.median(float(r['elapsed_ms']) for r in writes if r['configuration'] == name) for name in names]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8))
    for ax, values, title, unit in [(axes[0], sizes, 'Database footprint', 'MiB · includes table + indexes'),
                                    (axes[1], insert_ms, 'Insert maintenance cost', 'Median ms / 200 rows · rollback transaction')]:
        ax.barh(labels, values, color=colors, height=.58)
        ax.invert_yaxis()
        ax.set_title(title, loc='left', fontweight='bold', fontsize=17, pad=18)
        ax.set_xlabel(unit)
        ax.set_xlim(0, max(values) * 1.2)
        for i, value in enumerate(values):
            ax.text(value + max(values) * .02, i, f'{value:.2f}', va='center')
    fig.tight_layout(rect=(0, .07, 1, 1))
    export(fig, '02_storage_and_writes')

    depths = sorted({int(r['offset']) for r in pagination})
    fig, ax = plt.subplots(figsize=(12, 5.4))
    for method, color in [('offset', '#2865b3'), ('keyset', '#244a76')]:
        values = [statistics.median(float(r['elapsed_ms']) for r in pagination if r['method'] == method and int(r['offset']) == depth) for depth in depths]
        ax.plot(depths, values, marker='o', lw=2.5, color=color, label=method.title())
        for depth, value in zip(depths, values):
            ax.annotate(f'{value:.3f} ms', (depth, value), xytext=(0, 10), textcoords='offset points', ha='center', fontsize=9)
    ax.set_title('Deep-page access with an existing cursor', loc='left', fontweight='bold', fontsize=20, pad=20)
    ax.set_xlabel('Rows preceding the requested 50-row page')
    ax.set_ylabel('Median latency, ms')
    ax.set_ylim(0, ax.get_ylim()[1] * 1.18)
    ax.legend(frameon=False)
    ax.grid(axis='y', alpha=.15)
    fig.tight_layout(rect=(0, .07, 1, 1))
    export(fig, '03_pagination')

    fig, ax = plt.subplots(figsize=(12, 5.5))
    samples = [[float(r['elapsed_ms']) for r in raw if r['configuration'] == name and r['query'] == 'regional_sales'] for name in names]
    boxes = ax.boxplot(samples, tick_labels=labels, patch_artist=True, widths=.5, showfliers=True)
    for patch, color in zip(boxes['boxes'], colors):
        patch.set_facecolor(color)
    for line in boxes['medians']:
        line.set_color('#142a45')
        line.set_linewidth(2)
    ax.set_title('Regional sales: distribution across repeated reads', loc='left', fontweight='bold', fontsize=19, pad=20)
    ax.set_ylabel('Elapsed milliseconds')
    ax.grid(axis='y', alpha=.15)
    ax.set_axisbelow(True)
    fig.tight_layout(rect=(0, .07, 1, 1))
    export(fig, '04_sample_spread')

    median = lambda suite, query: float(next(r for r in summaries if r['configuration'] == suite and r['query'] == query)['median_ms'])
    regional_ratio = median('baseline', 'regional_sales') / median('partial', 'regional_sales')
    space_saved = sizes[3] - sizes[4]
    deep_offset = statistics.median(float(r['elapsed_ms']) for r in pagination if r['method'] == 'offset' and int(r['offset']) == depths[-1])
    deep_keyset = statistics.median(float(r['elapsed_ms']) for r in pagination if r['method'] == 'keyset' and int(r['offset']) == depths[-1])
    table = ''.join(f"<tr><td>{html.escape(r['configuration'])}</td><td>{html.escape(r['query'])}</td><td>{float(r['median_ms']):.4f}</td><td>{float(r['p95_ms']):.4f}</td><td>{r['n']}</td></tr>" for r in summaries)
    plan_for = lambda suite, query: '\n'.join(next(r['plan'] for r in plans if r['configuration'] == suite and r['query'] == query))
    comparisons = ''.join(f'<article><h3>{q.replace("_", " ").title()}</h3><div class="plan-pair"><div><b>Primary key only</b><pre>{html.escape(plan_for("baseline", q))}</pre></div><div><b>Partial queue suite</b><pre>{html.escape(plan_for("partial", q))}</pre></div></div></article>' for q in QUERIES)
    query_cards = ''.join(f'<details><summary>{q.replace("_", " ").title()} SQL</summary><pre>{html.escape(sql)}</pre></details>' for q, sql in QUERIES.items())
    html_report = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>SQLite index investigation</title><style>
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:80px}body{margin:0;background:#f1f5fa;color:#152536;font:16px/1.55 Segoe UI,Arial,sans-serif}header{position:sticky;top:0;z-index:2;background:#f1f5faf5;border-bottom:1px solid #c6d3e1;padding:16px 5%;display:flex;justify-content:space-between;gap:20px}header a{color:inherit;text-decoration:none;font-size:13px;margin-left:20px}header b{font-size:14px;letter-spacing:.05em}main{max-width:1320px;padding:0 52px;margin:auto}section{padding:64px 0;border-bottom:1px solid #c6d3e1;scroll-margin-top:35px}h1{font-size:62px;line-height:1.07;letter-spacing:-2.8px;max-width:940px;margin:12px 0 24px}h2{font-size:35px;line-height:1.15;letter-spacing:-1px;margin:10px 0 26px}h3{font-size:19px}p{max-width:950px}.eyebrow{font:12px Consolas,monospace;text-transform:uppercase;letter-spacing:.12em;color:#245d94}.lead{font-size:21px;max-width:930px;color:#52677f}.metrics{display:grid;grid-template-columns:repeat(4,1fr);margin:36px 0 22px;border-top:2px solid #1c3552;border-bottom:1px solid #c6d3e1}.metrics div{padding:18px 22px 18px 0}.metrics strong{display:block;font-size:36px;font-weight:500;letter-spacing:-1px}.metrics span{font-size:13px;color:#5e738b}.note{padding:16px 20px;border-left:3px solid #2865b3;background:#e3ecf7;font-size:15px}.chart{display:block;width:100%;height:auto;margin:24px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:28px}.plan-pair{display:grid;grid-template-columns:1fr 1fr;gap:22px}.plan-pair b{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#657c94}pre{background:#14283f;color:#e6f1ff;padding:20px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:13px/1.65 Consolas,monospace;border-radius:3px}article{border-top:1px solid #c6d3e1;padding:4px 0 10px}table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}td,th{padding:9px 12px;text-align:left;border-bottom:1px solid #cfdae8}th{font-size:12px;text-transform:uppercase;color:#657c94}td:nth-child(n+3),th:nth-child(n+3){text-align:right}summary{cursor:pointer;padding:14px 0;border-bottom:1px solid #c6d3e1;font-weight:600}a{color:#245d94}code{font-family:Consolas,monospace}footer{padding:30px 0 60px;font-size:13px;color:#657c94}@media(max-width:800px){main{padding:0 22px}header nav{display:none}h1{font-size:42px}.grid,.plan-pair{grid-template-columns:1fr}.metrics{grid-template-columns:1fr 1fr}section{padding:40px 0}}@media print{header{position:static}section{break-inside:avoid}details{display:block}}
</style></head><body><header><b>SQLITE / INDEX INVESTIGATION</b><nav><a href="#overview">Results</a><a href="#queries">Read timings</a><a href="#plans">Query plans</a><a href="#writes">Tradeoffs</a><a href="#pagination">Pagination</a><a href="#methods">Method</a></nav></header><main>
'''
    html_report += f'''<section id="overview"><div class="eyebrow">01 / measured experiment</div><h1>Read latency.<br>Index maintenance.<br>The cost of both.</h1><p class="lead">Five index designs, three production-shaped query patterns, one reproducible SQLite workload. Every configuration returns the same rows.</p><div class="metrics"><div><strong>{metadata['row_count']:,}</strong><span>synthetic orders</span></div><div><strong>5</strong><span>independent index configurations</span></div><div><strong>{len(raw):,}</strong><span>recorded query timing samples</span></div><div><strong>{regional_ratio:.1f}×</strong><span>regional-query median ratio, baseline / partial suite</span></div></div><p class="note">Measured on {metadata['os']} with SQLite {metadata['sqlite']}. Warm local reads; fixed parameters; no concurrency. Ratios describe this workload and machine, not a production guarantee.</p><img class="chart" src="charts/01_read_latency.png" alt="Median query latency by index suite, on logarithmic axes"></section>
<section id="queries"><div class="eyebrow">02 / read samples</div><h2>A single-column index did not improve the regional query.</h2><p>The regional query combines region, status and date. A region-only index still visits many table rows; the composite access path narrows the scan, and the covering variant removes table lookups. A temporary grouping B-tree remains.</p><div class="grid"><div><table><thead><tr><th>Configuration</th><th>Query</th><th>p50 ms</th><th>p95 ms</th><th>n</th></tr></thead><tbody>{table}</tbody></table></div><div>{query_cards}<p>Timing includes execution and fetching all returned rows. Sample p95 uses linear interpolation over {metadata['repetitions']} repetitions and is descriptive, not an SLA estimate.</p><p><a href="../results/read_timings.csv">Raw samples</a> · <a href="../results/result_checks.csv">Exact-result checksums</a></p></div></div><img class="chart" src="charts/04_sample_spread.png" alt="Regional query timing distribution"></section>
<section id="plans"><div class="eyebrow">03 / explain query plan</div><h2>From scans and sorting to ordered covering searches.</h2>{comparisons}<p>These are captured SQLite planner outputs. They explain access paths; they are not runtime operator profiles. <a href="../results/query_plans.json">Full plans with bound parameters</a> · <a href="../sql/index_suites.sql">All index definitions</a></p></section>
<section id="writes"><div class="eyebrow">04 / storage and maintenance</div><h2>The faster reads require additional work on insertion.</h2><img class="chart" src="charts/02_storage_and_writes.png" alt="Database size and insert maintenance timing by index suite"><p>The partial suite replaces the full queue index with an index containing open orders only ({metadata['status_counts']['open']:,} of {metadata['row_count']:,} rows). It uses <strong>{space_saved:.2f} MiB less</strong> than the covering suite while retaining the customer and regional covering indexes.</p><p class="note">Insert timings measure 200 inserts inside an existing transaction, followed by rollback outside the timer. They isolate statement and index-maintenance work. They exclude commit/fsync, concurrency and durable transaction throughput.</p><p><a href="../results/insert_timings.csv">Insert samples</a> · <a href="../results/storage.csv">File sizes and index-build times</a></p></section>
<section id="pagination"><div class="eyebrow">05 / equivalent page results</div><h2>A known cursor avoids skipping preceding rows.</h2><img class="chart" src="charts/03_pagination.png" alt="Offset versus keyset median latency across page depth"><div class="grid"><pre>SELECT id, created_at, amount_cents\nFROM orders\nORDER BY id\nLIMIT 50 OFFSET {depths[-1]};</pre><pre>SELECT id, created_at, amount_cents\nFROM orders\nWHERE id &gt; :previous_id\nORDER BY id\nLIMIT 50;</pre></div><p>At offset {depths[-1]:,}, the measured medians are {deep_offset:.3f} ms for offset and {deep_keyset:.3f} ms for keyset. The cursor is supplied before timing, as in sequential navigation. This does not provide arbitrary page-number access at keyset cost. The tests also cover deleted IDs and near-end pages.</p><p><a href="../results/pagination_checks.json">Page equality and plans</a> · <a href="../results/pagination_timings.csv">Raw pagination timings</a></p></section>
<section id="methods"><div class="eyebrow">06 / reproduction and limits</div><h2>Inspect the inputs. Re-run the measurements.</h2><div class="grid"><div><h3>Experiment controls</h3><ul><li>Seed {metadata['seed']}; one row per fictional order; timestamps have intentional ties.</li><li>Each suite starts from an identical database copy.</li><li>ANALYZE before measurement; automatic indexes disabled.</li><li>{metadata['warmups']} warmups and {metadata['repetitions']} measured reads per query/configuration.</li><li>32 MiB SQLite page cache; uncontrolled OS page cache.</li><li>Exact ordered result comparison before accepting timings.</li></ul><h3>Limits</h3><p>One process, one local run and fixed query parameters. Configuration order is seeded, not counterbalanced. The workload is synthetic and does not model skew, concurrent writes, network latency or a production service.</p></div><div><pre>python -m pip install -r requirements.txt\npython scripts/benchmark.py\npython scripts/render_report.py\npython -m unittest discover -s tests -v</pre><p><a href="../README.md">Repository guide</a> · <a href="../results/environment.json">Environment and run metadata</a> · <a href="decision-memo.md">Decision memo</a></p><p>AI-assisted portfolio investigation. Source code and reports were generated with assistance; numbers are actual local executions over explicitly synthetic data. No employer results or achieved business impact are claimed.</p></div></div></section><footer>Measured {html.escape(metadata['timestamp_utc'])} · Static report generated from committed CSV and JSON artifacts.</footer></main></body></html>'''
    from report_layout import responsive
    html_report = responsive(html_report)
    (ROOT / 'docs/report.html').write_text(html_report, encoding='utf-8')
    (ROOT / 'docs/decision-memo.md').write_text(f'''# Decision memo: access paths and their costs

## Result

The regional-sales median changes from **{median('baseline', 'regional_sales'):.3f} ms** with only the primary key to **{median('partial', 'regional_sales'):.3f} ms** in the final suite ({regional_ratio:.1f}× baseline/final ratio). The single-column suite measured **{median('single_column', 'regional_sales'):.3f} ms**: more indexes alone did not make that query faster.

The full covering suite occupies **{sizes[3]:.2f} MiB**. Replacing its queue index with an open-only partial index reduces this to **{sizes[4]:.2f} MiB**, saving **{space_saved:.2f} MiB** in this dataset. The customer and regional indexes are unchanged in that comparison. Insert-maintenance medians are **{insert_ms[0]:.3f} ms** for the baseline and **{insert_ms[4]:.3f} ms** for the final suite per 200 rows, excluding commit and rollback.

## Proposed design

For the three observed query patterns, retain ordered customer history and regional covering indexes. Use a partial queue index when the queue query keeps the exact `status = 'open'` predicate. Retain a full queue index instead if other statuses require the same access path. Do not extrapolate from the small timing difference between the covering and partial suites: the footprint reduction is direct, but their timing distributions and order effects need a larger experiment.

Use a last-seen primary-key cursor for sequential pagination. At a depth of {depths[-1]:,} preceding rows, offset/keyset medians were {deep_offset:.3f}/{deep_keyset:.3f} ms for identical 50-row results. Keyset requires a cursor and does not give arbitrary page-number access for free.

## Evidence and scope

- {metadata['row_count']:,} seeded synthetic orders; {metadata['repetitions']} samples per query/configuration; {metadata['warmups']} warmups.
- All index variants preserve exact result order, row count and checksum.
- Captured query plans show covering searches and the remaining temporary GROUP BY B-tree.
- Reads include `execute` and `fetchall`. Insertion measures statement/index work inside a transaction; rollback happens after timing.
- File sizes are measured after index creation and ANALYZE, before insertion trials.

## Limits and next experiment

This is one local, warmed-cache process with fixed query parameters and a seeded configuration order. It does not isolate disk throughput, durable commit cost, production p95, concurrency or network behavior. Identical indexes across the covering and partial suites can show different timings because of noise and cache/order effects. Run counterbalanced configurations across independent processes, skew customer popularity, vary time windows, and measure committed mixed read/write traffic before a production decision.

These are measured engineering observations over synthetic data, not real-business savings.
''', encoding='utf-8')
    print('Rendered four chart pairs, decision memo, and docs/report.html')


if __name__ == '__main__':
    render()
