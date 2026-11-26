"""An encrypted DB held by another writer is waited for, not failed at once (task:59d8a962)."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac import encdb  # noqa: E402

KEY = "ab" * 32


class BusyTimeoutTest(unittest.TestCase):
    def test_open_waits_for_an_exclusive_lock(self):
        apsw = encdb._binding()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "enc.sqlite"
            holder = apsw.Connection(str(path))
            holder.pragma("cipher", "sqlcipher")
            holder.pragma("hexkey", KEY)
            holder.execute("CREATE TABLE t (x)")
            holder.execute("BEGIN EXCLUSIVE")
            timer = threading.Timer(0.4, lambda: holder.execute("COMMIT"))
            timer.start()
            start = time.monotonic()
            con = encdb.open_db(path, key=KEY)
            self.assertGreaterEqual(time.monotonic() - start, 0.3)
            con.execute("INSERT INTO t VALUES (1)")
            con.commit()
            timer.join()
            con.close()
            holder.close()
