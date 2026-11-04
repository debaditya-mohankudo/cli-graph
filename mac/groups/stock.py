"""`mac stock` — stock and index market data kept in stock-tracker-mcp: NSE option-chain snapshots in stock-tracker-mcp's fii_dii.db.

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


def _run(code, *args):
    repo = Path(os.environ.get("MAC_STOCK_TRACKER_DIR", DEFAULT_REPO))
    if not (repo / "stock_tracker" / "utils" / "fii_dii.py").is_file():
        raise Failure("backend_missing", f"stock-tracker-mcp not found at {repo} (set MAC_STOCK_TRACKER_DIR)")
    proc = subprocess.run(["uv", "run", "--project", str(repo), "python", "-c", code, *args],
                          capture_output=True, text=True, cwd=repo)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        tail = " | ".join(proc.stderr.strip().splitlines()[-5:])
        raise Failure("tool_error", "stock verb gave no result" + (f" (stderr: {tail})" if tail else ""))


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
