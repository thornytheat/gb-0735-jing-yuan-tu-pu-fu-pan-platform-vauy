import unicodedata

from app.modules.coordinates.transform import integer
from app.reasons import classify

MISSING = {"", "-", "N/A", "NULL", "未知"}
RESULTS = {"PASS": "PASS", "P": "PASS", "通过": "PASS", "FAIL": "FAIL", "F": "FAIL", "失败": "FAIL"}


def interpret(fields):
    """Pure parse of one raw row. Returns (measurement | None, reason code | None)."""
    try:
        attempt = integer(fields["attempt"])
        if not 1 <= attempt <= 999:
            raise ValueError
    except (KeyError, ValueError):
        return None, "BAD_ATTEMPT"
    token = unicodedata.normalize("NFKC", fields.get("result", "")).strip().upper()
    if token in MISSING:
        return None, "NO_RESULT"
    if token not in RESULTS:
        return None, "BAD_RESULT"
    result = RESULTS[token]
    try:
        bin_code = integer(fields.get("bin", ""))
        if not (bin_code == 1 if result == "PASS" else 2 <= bin_code <= 999):
            raise ValueError
    except ValueError:
        return None, "BAD_BIN"
    return {"attempt": attempt, "result": result, "bin": bin_code}, None


def measure(row):
    value, code = interpret(row.get("fields", {}))
    if code is not None:
        classify(row, "isolated", code)
        return None
    row["measurement"] = value
    return value["attempt"], value["result"], value["bin"]
