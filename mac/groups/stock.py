"""`mac stock` — stock and index market data kept in stock-tracker-mcp: NSE option-chain snapshots in stock-tracker-mcp's fii_dii.db, and US-listed quotes and recent performance through its yfinance code.

stock-tracker-mcp's stock_tracker/utils/fii_dii.py stays the one implementation:
each verb runs it in that repo's own environment (`uv run --project`) and
returns its JSON result. `MAC_STOCK_TRACKER_DIR` overrides the repo path.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

from mac.contract import Failure

UNSET = argparse.SUPPRESS
DEFAULT_REPO = Path.home() / "workspace" / "stock-tracker-mcp"

_CHAIN_API = """
import json, sys
from stock_tracker.utils import fii_dii as f
rows = f.capture_chain_api(*sys.argv[1:])
stored = f.upsert_option_chain(rows)
snaps = sorted({(r["symbol"], r["snap_ts"], r["expiry"]) for r in rows})
print(json.dumps({"stored": stored, "snapshots": [
    {**f.chain_walls(ts, sym, expiry=ex),
     "max_pain": f.chain_max_pain(ts, sym, expiry=ex)["max_pain"]} for sym, ts, ex in snaps]}))
"""

_WALLS = """
import json, sys
from stock_tracker.utils import fii_dii as f
a = [None if v == "" else v for v in sys.argv[1:]]
ts, sym, ex = (a + [None] * 3)[:3]
sym = sym or "NIFTY"
w = f.chain_walls(ts, sym, expiry=ex)
print(json.dumps({**w, "max_pain": f.chain_max_pain(w["snap_ts"], sym, expiry=w["expiry"])["max_pain"]}))
"""


_US_QUOTE = """
import json, sys
import yfinance as yf
from stock_tracker.utils.update_run import fetch_live_quote
from stock_tracker.utils.trading_date import effective_trading_datetime, market_close
# NYSE calendar for every ticker (Nasdaq shares its hours); holiday-aware, live time only mid-session
now = effective_trading_datetime(exchange="NYSE")
session_open = now.time() < market_close("NYSE")
out = []
for t in sys.argv[1:]:
    t = t.upper()
    try:
        q = fetch_live_quote(t)
        h = yf.Ticker(t).history(period="5d")["Close"]
        prev = float(h.iloc[-2]) if len(h) > 1 else None
        q.update(ticker=t, prev_close=round(prev, 2) if prev else None,
                 change_pct=round((q["close"] / prev - 1) * 100, 2) if prev else None,
                 intraday=session_open and q["date"] == now.date().isoformat())
        out.append(q)
    except Exception as e:
        out.append({"ticker": t, "error": str(e)})
print(json.dumps({"as_of": now.isoformat(timespec="seconds"), "session_open": session_open, "quotes": out}))
"""

_US_PERF = """
import json, sys
import yfinance as yf
t, n = sys.argv[1].upper(), int(sys.argv[2])
h = yf.Ticker(t).history(period="2y")["Close"].dropna()
if len(h) < 30:
    raise SystemExit(f"not enough history for {t}")
last = float(h.iloc[-1])
pct = lambda a, b: round((float(a) / float(b) - 1) * 100, 2)
ret = {lbl: pct(last, h.iloc[-1 - k]) for lbl, k in
       [("1d", 1), ("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252)] if len(h) > k}
ret["ytd"] = pct(last, h[h.index.year == h.index[-1].year].iloc[0])
y = h.iloc[-252:]
hi, lo = float(y.max()), float(y.min())
d50, d200 = float(h.iloc[-50:].mean()), float(h.iloc[-200:].mean())
print(json.dumps({
    "ticker": t, "date": str(h.index[-1].date()), "close": round(last, 2), "returns_pct": ret,
    "high_52w": {"price": round(hi, 2), "date": str(y.idxmax().date()), "off_pct": pct(last, hi)},
    "low_52w": {"price": round(lo, 2), "date": str(y.idxmin().date()), "above_pct": pct(last, lo)},
    "dma_50": {"price": round(d50, 2), "vs_pct": pct(last, d50)},
    "dma_200": {"price": round(d200, 2), "vs_pct": pct(last, d200)},
    "vol_1m_annualized_pct": round(float(h.pct_change().iloc[-21:].std()) * 252 ** 0.5 * 100, 1),
    "closes": [{"date": str(i.date()), "close": round(float(v), 2)} for i, v in h.iloc[-n:].items()],
}))
"""


def run_in_repo(python_args, *, marker, label):
    """Run `python <python_args>` in stock-tracker-mcp's environment and return
    the JSON object on the last stdout line. Shared by `mac stock` and `mac graph_metrics`;
    `marker` is the stock_tracker/utils file the verb needs."""
    repo = Path(os.environ.get("MAC_STOCK_TRACKER_DIR", DEFAULT_REPO))
    if not (repo / "stock_tracker" / "utils" / marker).is_file():
        raise Failure("backend_missing", f"stock-tracker-mcp not found at {repo} (set MAC_STOCK_TRACKER_DIR)")
    proc = subprocess.run(["uv", "run", "--project", str(repo), "python", *python_args],
                          capture_output=True, text=True, cwd=repo)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        tail = " | ".join(proc.stderr.strip().splitlines()[-5:])
        raise Failure("tool_error", f"{label} gave no result" + (f" (stderr: {tail})" if tail else ""))


def _run(code, *args):
    return run_in_repo(["-c", code, *args], marker="fii_dii.py", label="stock verb")


def register(registry):
    @registry.verb("stock", "fii_dii_chain_api", mode="write",
                   desc="fetch the live NSE option chain for an index or F&O stock (nearest expiry) from the page open in Safari, store it in option_chain_snap and return its OI walls, PCR and max pain",
                   args=lambda p: p.add_argument("symbols", nargs="*", help="NIFTY, BANKNIFTY, MIDCPNIFTY or a stock such as PAYTM (default NIFTY MIDCPNIFTY); needs an nseindia page open in Safari's front tab"))
    def chain_api(ns):
        return _run(_CHAIN_API, *ns.symbols)

    def walls_args(p):
        p.add_argument("symbol", nargs="?", default="NIFTY", help="default NIFTY")
        p.add_argument("--snap-ts", default=UNSET, help="YYYY-MM-DDTHH:MM:SS (default: latest stored for the symbol)")
        p.add_argument("--expiry", default=UNSET, help="YYYY-MM-DD (default: latest stored under the snapshot)")

    @registry.verb("stock", "fii_dii_chain_walls", mode="read",
                   desc="top call/put OI strikes, PCR and max pain of a stored option-chain snapshot (default: latest for the symbol)",
                   args=walls_args)
    def chain_walls(ns):
        return _run(_WALLS, getattr(ns, "snap_ts", ""), ns.symbol, getattr(ns, "expiry", ""))

    @registry.verb("stock", "us_quote", mode="read",
                   desc="live price quote of US-listed stocks or ETFs (NYSE, Nasdaq): last price, open/high/low, volume, previous close, day change %, P/E and market cap",
                   args=lambda p: p.add_argument("tickers", nargs="+", help="US tickers such as AAPL EWY SPY"))
    def us_quote(ns):
        return _run(_US_QUOTE, *ns.tickers)

    def perf_args(p):
        p.add_argument("ticker", help="US ticker such as EWY or AAPL")
        p.add_argument("--closes", type=int, default=8, help="number of recent daily closes to include (default 8)")

    @registry.verb("stock", "us_performance", mode="read",
                   desc="recent performance of a US-listed stock or ETF: 1 day to 1 year and year-to-date returns, 52-week high/low, 50/200-day moving averages, 1-month volatility and recent daily closes",
                   args=perf_args)
    def us_performance(ns):
        return _run(_US_PERF, ns.ticker, str(ns.closes))
