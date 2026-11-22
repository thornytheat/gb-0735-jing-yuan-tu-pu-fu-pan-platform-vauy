"""Per-die review of the edge retention band.

The physical mask keeps an annular band of dies outside the valid population
(``EDGE_EXCLUSION``).  A blanket narrowing of ``edge`` would re-admit the whole
ring at once, including dies with no evidence and dies that failed repeatedly.
This module inspects every band position individually from its raw retest rows
so a reviewer can decide cell by cell.
"""

from collections import defaultdict

from app.modules.retest.measurements import interpret
from app.reasons import REASONS

RECOVER = "RECOVER"
RETAIN = "RETAIN"

# A position may enter a recovery conclusion only when the adjudicated latest
# measurement is a pass.  Failing bands and conflicts keep their place in the
# retention band; the value is never forced back to PASS.
RECOVERABLE = {"RECOVERED"}


def _ordered(rows):
    return sorted(rows, key=lambda row: (row["source"], row["line"]))


def _evidence(row):
    fields = row.get("fields") or {}
    value, code = interpret(fields) if fields else (None, row.get("code"))
    entry = {
        "id": row["id"], "source": row["source"], "line": row["line"],
        "end_line": row.get("end_line", row["line"]),
        "attempt": fields.get("attempt"), "result": fields.get("result"),
        "bin": fields.get("bin"), "note": fields.get("note"),
        "usable": value is not None, "code": code,
        "measurement": value,
    }
    return entry


def inspect_rows(rows):
    """Adjudicate one edge position from its rows without mutating them.

    Mirrors ``arbitrate.decide``: only parseable measurements take part,
    attempts are compared numerically and a same-attempt split becomes a
    conflict.  Returns the full attempt chain plus a per-die recommendation.
    """
    ordered = _ordered(rows)
    evidence = [_evidence(row) for row in ordered]
    attempts = defaultdict(list)
    for row, entry in zip(ordered, evidence):
        if entry["measurement"] is not None:
            attempts[entry["measurement"]["attempt"]].append((row, entry["measurement"]))
    history = []
    for attempt in sorted(attempts):
        members = sorted(attempts[attempt], key=lambda item: (item[0]["source"], item[0]["line"]))
        values = {(value["result"], value["bin"]) for _, value in members}
        result, bin_code = next(iter(values)) if len(values) == 1 else ("CONFLICT", None)
        history.append({"attempt": attempt, "result": result, "bin": bin_code,
                        "evidence": [row["id"] for row, _ in members]})

    if not ordered:
        state = "NO_EDGE_EVIDENCE"
    elif not history:
        state = "BAD_EDGE_MEASUREMENT"
    elif history[-1]["result"] == "CONFLICT":
        state = "EDGE_CONFLICT"
    elif history[-1]["result"] == "FAIL":
        trailing = 0
        for step in reversed(history):
            if step["result"] != "FAIL":
                break
            trailing += 1
        state = "REPEATED_EDGE_FAILURE" if trailing >= 2 else "EDGE_FAILURE"
    else:
        state = "RECOVERED"

    latest = history[-1] if history else None
    return {
        "state": state,
        "reason": REASONS[state],
        "recoverable": state in RECOVERABLE,
        "recommend": RECOVER if state == "RECOVERED" else RETAIN,
        "result": latest["result"] if latest else None,
        "bin": latest["bin"] if latest else None,
        "attempt": latest["attempt"] if latest else None,
        "history": history,
        "evidence": evidence,
        "evidence_ids": [entry["id"] for entry in evidence],
    }


def scan(snapshot):
    """List every edge-band position with its evidence and recommendation."""
    wafers = []
    cells = []
    by_wafer = defaultdict(lambda: defaultdict(list))
    for row in snapshot["rows"]:
        if "transform" in row:
            by_wafer[row["wafer"]][tuple(row["transform"]["canonical"])].append(row)
    for wafer, mask in snapshot["masks"].items():
        edge = [(x, y) for x, y, eligibility in mask["cells"] if eligibility == "EDGE_EXCLUSION"]
        rows_by_point = by_wafer[wafer]
        wafer_cells = []
        for x, y in edge:
            detail = inspect_rows(rows_by_point.get((x, y), []))
            wafer_cells.append({"wafer": wafer, "x": x, "y": y, **detail})
        cells.extend(wafer_cells)
        wafers.append({"wafer": wafer, "edge_cells": len(edge),
                       "recoverable": sum(1 for cell in wafer_cells if cell["recommend"] == RECOVER),
                       "with_evidence": sum(1 for cell in wafer_cells if cell["evidence"])})
    return {"wafers": wafers, "cells": cells,
            "recoverable": [[cell["wafer"], cell["x"], cell["y"]] for cell in cells
                            if cell["recommend"] == RECOVER]}
