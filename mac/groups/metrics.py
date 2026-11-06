"""`mac metrics` — the dated metric store behind stock-tracker-mcp's ontology graphs (graph_metrics.db): market-data loaders, freshness and series queries, and hand-entered prints.

stock-tracker-mcp's stock_tracker/utils/graph_metrics.py stays the one
implementation: each verb runs `python -m stock_tracker.utils.graph_metrics
--json <subcommand> ...` in that repo's environment (`uv run --project`) and
returns the one JSON object it prints. Options a caller leaves out are not
passed, so graph_metrics keeps its own defaults. `MAC_STOCK_TRACKER_DIR`
overrides the repo path.
"""
from pathlib import Path

from mac.contract import Failure
from mac.groups.stock import UNSET, run_in_repo

MODULE = "stock_tracker.utils.graph_metrics"
AMFI_FIELDS = ("fof_net_flow", "fof_aum", "etf_net_flow", "etf_aum")  # Rs crore, in graph_metrics' order


def _run(cmd, *args):
    result = run_in_repo(["-m", MODULE, "--json", cmd, *args], marker="graph_metrics.py",
                         label=f"graph_metrics {cmd}")
    if "error" in result:
        raise Failure("tool_error", f"graph_metrics {cmd}: {result['error']}")
    return result


def _opts(ns, *dests, **flags):
    """argv for the options the caller set. A dest maps to `--<dest with dashes>`;
    `flags` names the odd one out (dest=flag). A bool dest is a bare flag."""
    out = []
    for dest in (*dests, *flags):
        if not hasattr(ns, dest):
            continue
        val, flag = getattr(ns, dest), flags.get(dest, "--" + dest.replace("_", "-"))
        if val is True:
            out.append(flag)
        elif val is not False:
            out += [flag, str(val)]
    return out


def _abs(path):
    """graph_metrics runs with cwd = its repo, so a caller's relative path is resolved here."""
    return str(Path(path).expanduser().resolve())


def _start(p):
    p.add_argument("--start", default=UNSET, help="YYYY-MM-DD (default: resume from what is stored)")


def _graph_file(p, help_text):
    p.add_argument("--graph-file", default=UNSET, help=help_text)


# (verb, graph_metrics subcommand, description) for the incremental loaders that take --start
LOADERS = [
    ("load_us_macro", "load-us-macro",
     "load the shared US macro series (fed funds rate, Treasury yields, dollar index, crude, gold, ACM term premium, real yield) into the graph metric store, incrementally; returns rows written, failed legs and a Safari FRED fallback when FRED is unreachable"),
    ("load_us_open", "load-us-open",
     "load settled Asia and Europe index closes and US index futures for the US market open graph into the metric store, incrementally; returns rows written and failed legs"),
    ("load_fed", "load-fed",
     "load the Fed rate-hike graph's FRED series (real rate, breakeven inflation, mortgage rate PMMS, GDPNow) into the metric store, incrementally; returns rows written, failed legs and a Safari FRED fallback"),
    ("load_fii_flows", "load-fii-flows",
     "load FII/DII cash and participant open interest from fii_dii.db plus India VIX onto the FII flows graph's nodes in the metric store, incrementally"),
    ("load_ai_capex", "load-ai-capex",
     "load closes, Treasury yields and high-yield credit spreads (HY OAS) for the AI capex cycle and bubble graphs into the metric store, incrementally; returns rows written, failed legs and a Safari FRED fallback"),
    ("load_etf_premium", "load-etf-premium",
     "load the premium or discount of Indian overseas ETFs to their AMFI NAV for the India risk regime graph, incrementally; returns rows written and each ETF's latest premium"),
    ("load_treasury_par", "load-treasury-par",
     "load the US Treasury daily par yield curve (2y, 10y, 30y) into the metric store, incrementally; returns rows written and the latest yields"),
]


def register(registry):
    for verb, cmd, desc in LOADERS:
        @registry.verb("metrics", verb, mode="write", desc=desc, args=_start)
        def handler(ns, cmd=cmd):
            return _run(cmd, *_opts(ns, "start"))

    @registry.verb("metrics", "load_kalshi", mode="write",
                   desc="load Kalshi prediction-market odds for the next FOMC Fed rate decision (hike, hold, cut) into the Fed rate-hike graph's metric store; returns rows written and each outcome's probability",
                   args=lambda p: p.add_argument("--event", default=UNSET, help="Kalshi event ticker (default: graph_metrics' current FOMC event)"))
    def load_kalshi(ns):
        return _run("load-kalshi", *_opts(ns, "event"))

    @registry.verb("metrics", "load_flows", mode="write",
                   desc="load FII index-futures open interest and FII/DII cash flows from fii_dii.db onto the India market open graph's metric store; returns rows written per table")
    def load_flows(ns):
        return _run("load-flows")

    @registry.verb("metrics", "load_bhavcopy", mode="write",
                   desc="load Nifty futures basis and option-chain positioning from NSE UDiFF F&O bhavcopy files (.csv or .csv.zip) into the India market open graph's metric store",
                   args=lambda p: p.add_argument("paths", nargs="+", help="bhavcopy files"))
    def load_bhavcopy(ns):
        return _run("load-bhavcopy", *[_abs(p) for p in ns.paths])

    @registry.verb("metrics", "ingest_fred", mode="write",
                   desc="store a FRED pull fetched in Safari (the JSON a loader's Safari fallback leaves in window.__fred, saved to a file) into the graph metric store",
                   args=lambda p: p.add_argument("path", help="JSON file of {series_id: [[date, value], ...]}"))
    def ingest_fred(ns):
        return _run("ingest-fred", _abs(ns.path))

    def record_args(p):
        p.add_argument("node_id")
        p.add_argument("metric")
        p.add_argument("as_of", help="YYYY-MM-DD")
        p.add_argument("value", type=float)
        p.add_argument("unit")
        p.add_argument("source", help="where the figure came from")
        p.add_argument("--confidence", default=UNSET, choices=("primary", "secondary", "contested"),
                       help="default secondary")
        _graph_file(p, "default: us-macro for a shared plug node, ai-capex for an ai-capex node, else required")

    @registry.verb("metrics", "record", mode="write",
                   desc="record one hand-entered figure (rate-hike odds, a CDS level, any print with no feed) for a graph node in the metric store, source-tagged",
                   args=record_args)
    def record(ns):
        return _run("record", ns.node_id, ns.metric, ns.as_of, str(ns.value), ns.unit, ns.source,
                    *_opts(ns, "confidence", "graph_file"))

    def amfi_args(p):
        p.add_argument("month", help="YYYY-MM")
        for f in AMFI_FIELDS:
            p.add_argument(f, type=float, help="Rs crore")
        p.add_argument("source", help='e.g. "AMFI Monthly Note Sep 2026 p15"')

    @registry.verb("metrics", "record_amfi_overseas", mode="write",
                   desc="record one month of AMFI overseas fund-of-fund and overseas ETF net flow and AUM (Rs crore) in the metric store",
                   args=amfi_args)
    def record_amfi_overseas(ns):
        return _run("record-amfi-overseas", ns.month, *(str(getattr(ns, f)) for f in AMFI_FIELDS), ns.source)

    def series_args(p):
        p.add_argument("node_id", help="graph node id, e.g. us_treasury_yields")
        p.add_argument("--metric", default=UNSET)
        _graph_file(p, "omit to see every graph's rows (shared plug nodes live under us-macro)")
        p.add_argument("--rows", type=int, default=UNSET, help="max rows, newest first (default 30)")

    @registry.verb("metrics", "series", mode="read",
                   desc="stored date series of one graph node's metrics from the metric store, newest first; an empty result says which other graph stores that node",
                   args=series_args)
    def series(ns):
        return _run("series", ns.node_id,
                    *_opts(ns, "metric", "graph_file", rows="--limit"))

    def latest_args(p):
        _graph_file(p, "default: the India market open graph")
        p.add_argument("--as-of", default=UNSET, help="YYYY-MM-DD (default: the newest stored session)")

    @registry.verb("metrics", "latest", mode="read",
                   desc="every node's latest stored metric values for one session of a graph, as {node: {metric: value}}",
                   args=latest_args)
    def latest(ns):
        return _run("latest", *_opts(ns, "graph_file", "as_of"))

    def fresh_args(p):
        _graph_file(p, "default: every graph")
        p.add_argument("--stale-only", action="store_true", default=UNSET,
                       help="only metrics older than the last NSE session")
        p.add_argument("--node", default=UNSET, help="substring filter on node id or metric")

    @registry.verb("metrics", "freshness", mode="read",
                   desc="which graph metrics are stale or current: newest stored date, source and row count per node and metric, checked against the last NSE session; run before any fallback fetch",
                   args=fresh_args)
    def freshness(ns):
        return _run("freshness", *_opts(ns, "graph_file", "stale_only", "node"))
