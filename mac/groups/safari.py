"""`mac safari` — Safari via the local-mac safari__* handlers, with the tab guard enforced.

Every Safari handler that acts on a page (navigate, js, read, screenshot,
close_tab, reload, back, forward) targets the front window's current tab, and
that tab is usually the user's own. So those verbs require --expect-host: before
running, the verb reads the front tab's URL and refuses with 'blocked' unless
its host is that host or a subdomain of it (a leading www. is ignored). An
unguarded call to them cannot be written (task:0c64fa90).

current_url, current_title and list_tabs stay unguarded: they are how you find
out what is in front. open needs no guard because it makes a new tab or window;
--new-window brings it to the front, which is what makes the guarded verbs land
on it. close_all_tabs is write and unguarded; it closes everything.

The check and the action are two osascript calls, so a tab switch between them
is still possible, though the gap is milliseconds.

Hand-written, outside tools/gen_groups.py, for the guard. Optional flags default
to argparse.SUPPRESS and are forwarded with given(), so handler defaults apply.
"""
import argparse
from urllib.parse import urlparse

from mac.contract import Failure
from mac.groups._backend import call, given

UNSET = argparse.SUPPRESS


def _bare(host):
    host = (host or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def host_matches(url, expected):
    """True when url's host is `expected` or a subdomain of it, ignoring a leading www."""
    host, want = _bare(urlparse(url.strip()).hostname), _bare(expected)
    return bool(host) and bool(want) and (host == want or host.endswith("." + want))


def guard(ns):
    """Refuse unless the front tab is on --expect-host."""
    url = call("safari", "current_url")
    url = url.strip() if isinstance(url, str) else ""
    if not host_matches(url, ns.expect_host):
        raise Failure("blocked",
                      f"front tab is {url or '(no URL)'!r}, not {ns.expect_host!r}; "
                      "it may be the user's tab. Open yours with `mac safari open <url> --new-window` "
                      "or ask the user to bring it to the front.")


def _expect_host(p):
    p.add_argument("--expect-host", required=True, metavar="HOST",
                   help="refuse unless the front tab's host is HOST or a subdomain of it")


def register(registry):
    def open_args(p):
        p.add_argument("url")
        p.add_argument("--new-window", default=UNSET, action="store_true",
                       help="open in a new front window, so guarded verbs act on it")

    @registry.verb("safari", "open", mode="write",
                   desc="open a URL in a new Safari tab (allowlist enforced)", args=open_args)
    def open_url(ns):
        return call("safari", "open", **given(ns, ("url", "new_window")))

    @registry.verb("safari", "current_url", mode="read", desc="URL of Safari's front tab")
    def current_url(ns):
        return call("safari", "current_url")

    @registry.verb("safari", "current_title", mode="read", desc="title of Safari's front tab")
    def current_title(ns):
        return call("safari", "current_title")

    @registry.verb("safari", "list_tabs", mode="read", desc="list all open Safari tabs")
    def list_tabs(ns):
        return call("safari", "list_tabs")

    @registry.verb("safari", "close_all_tabs", mode="write",
                   desc="close every Safari tab, including the user's")
    def close_all_tabs(ns):
        return call("safari", "close_all_tabs")

    def guarded(action, mode, desc, args=None, params=()):
        """A verb acting on the front tab: --expect-host is required and checked first."""
        def configure(p):
            if args:
                args(p)
            _expect_host(p)

        @registry.verb("safari", action, mode=mode, desc=desc, args=configure)
        def run(ns):
            guard(ns)
            return call("safari", action, **given(ns, params))
        return run

    guarded("navigate", "write", "navigate the front tab to a URL (allowlist enforced)",
            lambda p: p.add_argument("url"), ("url",))
    guarded("close_tab", "write", "close the front tab")
    guarded("reload", "write", "reload the front tab")
    guarded("back", "write", "go back in the front tab")
    guarded("forward", "write", "go forward in the front tab")
    guarded("js", "write", "run JavaScript in the front tab",
            lambda p: p.add_argument("js"), ("js",))
    guarded("read", "read", "read the front tab: text, html, links, title or selected",
            lambda p: p.add_argument("mode", help="text|html|links|title|selected"),
            ("mode",))
    guarded("screenshot", "read", "screenshot the front tab to a PNG file",
            lambda p: p.add_argument("--outfile", default=UNSET), ("outfile",))
