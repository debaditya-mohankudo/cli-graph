"""`mac kospi` — the Korean market interface: KOSPI closes, KRX foreign/institution/retail
flows (cash and KOSPI 200 futures), foreign holding of SK hynix and Samsung, and the
Nifty vs KOSPI pair lens built on them.

stock-tracker-mcp stays the one implementation: `stock_tracker.utils.krx` (Naver data,
cached in fii_dii.db) and `stock_tracker.utils.nifty_kospi_pair` (the pair checklist).
Each verb runs `python -m <module> --json <subcommand> ...` in that repo's environment
and returns the one JSON object it prints. Options a caller leaves out are not passed,
so the modules keep their own defaults. `MAC_STOCK_TRACKER_DIR` overrides the repo path.
"""
from mac.contract import Failure
from mac.groups.stock import UNSET, run_in_repo

KRX = ("stock_tracker.utils.krx", "krx.py")
PAIR = ("stock_tracker.utils.nifty_kospi_pair", "nifty_kospi_pair.py")


def _run(target, cmd, *args):
    module, marker = target
    result = run_in_repo(["-m", module, "--json", cmd, *args], marker=marker, label=f"kospi {cmd}")
    if "error" in result:
        raise Failure("tool_error", f"kospi {cmd}: {result['error']}")
    return result


def _opt(ns, dest, flag=None):
    val = getattr(ns, dest, UNSET)
    return [] if val is UNSET else [flag or "--" + dest.replace("_", "-"), str(val)]


def _int_arg(flag, help_text):
    return lambda p: p.add_argument(flag, type=int, default=UNSET, help=help_text)


def register(registry):
    @registry.verb("kospi", "index", mode="read",
                   desc="KOSPI index daily closes and % change for recent Korean market sessions (KRX holidays left out)",
                   args=_int_arg("--days", "calendar days back (default 10)"))
    def index(ns):
        return _run(KRX, "index", *_opt(ns, "days"))

    @registry.verb("kospi", "flows", mode="write",
                   desc="foreign, institution and retail net buying in the KOSPI cash market and foreign net buying of KOSPI 200 futures per session (100m KRW), with totals; fetches missing days from Naver into fii_dii.db",
                   args=_int_arg("--days", "calendar days back (default 10)"))
    def flows(ns):
        return _run(KRX, "flows", *_opt(ns, "days"))

    def hold_args(p):
        p.add_argument("--code", default=UNSET, help="KRX stock code (default 000660 SK hynix; 005930 Samsung)")
        _int_arg("--days", "sessions (default 10)")(p)

    @registry.verb("kospi", "hold", mode="write",
                   desc="foreign investor holding % of SK hynix or Samsung Electronics per session and its change, a sign of whether foreigners are still exiting Korean chip stocks",
                   args=hold_args)
    def hold(ns):
        return _run(KRX, "hold", *_opt(ns, "code"), *_opt(ns, "days"))

    @registry.verb("kospi", "backfill", mode="write",
                   desc="backfill KRX investor flows (KOSPI cash and KOSPI 200 futures) and SK hynix / Samsung foreign holding into fii_dii.db for the last N days; only missing sessions are fetched",
                   args=_int_arg("--days", "calendar days back (default 31)"))
    def backfill(ns):
        return _run(KRX, "backfill", *_opt(ns, "days"))

    @registry.verb("kospi", "pair", mode="write",
                   desc="Nifty vs KOSPI pair-trade lens: spread and z-score, FII Nifty futures short, Brent, SOX, India VIX, Korean foreign flows, and the long-Nifty / short-KOSPI entry and exit checklist",
                   args=_int_arg("--sessions", "KRX sessions in the flow window (default 5)"))
    def pair(ns):
        return _run(PAIR, "pair", *_opt(ns, "sessions"))

    @registry.verb("kospi", "pair_history", mode="write",
                   desc="replay the Nifty vs KOSPI pair checklist on each recent session: spread, z-score, FII net short and entry/exit scores per day",
                   args=_int_arg("--sessions", "sessions to replay (default 20)"))
    def pair_history(ns):
        return _run(PAIR, "history", *_opt(ns, "sessions"))
