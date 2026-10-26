"""Output and failure contract shared by every verb."""
import json

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
DEFAULT_LIMIT = 100


class Failure(Exception):
    def __init__(self, code, message, status=EXIT_ERROR):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def error_object(code, message):
    return {"error": {"code": code, "message": message}}


def raise_if_error(result):
    """A tool result that is a dict with an "error" key is a failure, whichever backend ran it."""
    if isinstance(result, dict) and "error" in result:
        raise Failure("tool_error", str(result["error"]))
    return result


def apply_limit(data, limit):
    """Cut a list result to `limit` items; returns (data, truncation or None)."""
    if not isinstance(data, list):
        return data, None
    limit = DEFAULT_LIMIT if limit is None else limit
    if len(data) <= limit:
        return data, None
    return data[:limit], {"shown": limit, "total": len(data)}


def dump(data):
    return json.dumps(data, ensure_ascii=False, default=str)
