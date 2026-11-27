"""Suite-wide setup: calls made through mac.cli.main in tests must not land in
the real mcp_tool_calls log (task:80010ea1). Tests of the logging itself clear
this in their own scope."""
import os
import tempfile

os.environ["MAC_NO_CALL_LOG"] = "1"

# No test may write derived DB keys into ~/.claude/encdb-cache (task:d2330f3a).
os.environ["ENCDB_CACHE_DIR"] = tempfile.mkdtemp(prefix="encdb-cache-")
