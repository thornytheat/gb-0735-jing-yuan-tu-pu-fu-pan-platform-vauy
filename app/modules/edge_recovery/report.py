"""Derive a recovered snapshot from an archived run without touching it.

The archived run is immutable.  A recovery conclusion is a *new* artefact that
re-reads the pinned source, re-admits exactly the selected edge positions to the
valid population at their adjudicated result, and recomputes decisions,
clusters and the yield/ledger reconciliation from there.
"""

from collections import Counter

from app.modules.clusters.components import components
from app.modules.coordinates.transform import align
from app.modules.edge_recovery.analysis import RECOVER, inspect_rows, scan
from app.modules.intake.reader import ingest
from app.modules.mask.geometry import screen
from app.modules.retest.arbitrate import arbitrate
from app.modules.yield_audit.compare import compare
from app.reasons import REASONS

EDGE = "EDGE_EXCLUSION"


def _requested(selection, preview):
    """Validate a reviewer selection against the preview and normalize order."""
    allowed = {(cell["wafer"], cell["x"], cell["y"]): cell for cell in preview["cells"]}
    chosen = []
    seen = set()
    for item in selection:
        if len(item) != 3:
            raise ValueError("收回位须为 [晶圆, x, y]")
        try:
            key = (str(item[0]), int(item[1]), int(item[2]))
        except (TypeError, ValueError) as exc:
            raise ValueError("收回位须为 [晶圆, 整数 x, 整数 y]") from exc
        if key in seen:
            continue
        seen.add(key)
        cell = allowed.get(key)
        if cell is None:
            raise ValueError(f"{key[0]} ({key[1]},{key[2]}) 不在边缘保留带")
        if cell["recommend"] != RECOVER or not cell["recoverable"]:
            raise ValueError(f"{key[0]} ({key[1]},{key[2]}) 证据不足以收回：{cell['reason']}")
        chosen.append(list(key))
    return sorted(chosen)


def recalculate(package, selection=None):
    """Return (derived snapshot, conclusion detail) for one recovery selection.

    Rebuilds from the pinned input so every measured row starts as an eligible
    candidate again; the archived ``bucket`` values are never reused.
    """
    rows, files = ingest(package)
    transforms = align(package.spec, rows)
    masks = screen(package.spec, rows)
    preview = scan({"masks": masks, "rows": rows})
    chosen = _requested(selection if selection is not None else preview["recoverable"], preview)
    recovered = {(wafer, x, y) for wafer, x, y in chosen}

    for row in rows:
        if "transform" not in row:
            continue
        key = (row["wafer"], *row["transform"]["canonical"])
        if key in recovered and row.get("code") == EDGE:
            row["bucket"] = "candidate"
            row.pop("code", None)
            row.pop("reason", None)

    for wafer, mask in masks.items():
        cells = []
        for x, y, eligibility in mask["cells"]:
            if eligibility == EDGE and (wafer, x, y) in recovered:
                eligibility = "ACTIVE"
            cells.append((x, y, eligibility))
        masks[wafer] = {"geometry": mask["geometry"], "cells": cells,
                        "counts": dict(Counter(cell[2] for cell in cells))}

    decisions = arbitrate(masks, rows)
    clusters = {wafer: components(cells) for wafer, cells in decisions.items()}
    audit = compare(package.spec, masks, decisions, rows, files)
    reasons = Counter(row["code"] for row in rows if row["bucket"] == "isolated")
    derived = {"files": files, "transforms": transforms, "masks": masks, "decisions": decisions,
               "clusters": clusters, "audit": audit,
               "reasons": dict(sorted(reasons.items())), "rows": rows}

    evidence_by_point = {}
    for row in rows:
        if "transform" in row:
            evidence_by_point.setdefault((row["wafer"], *row["transform"]["canonical"]), []).append(row)

    recovered_detail = []
    for wafer, x, y in chosen:
        detail = inspect_rows(evidence_by_point.get((wafer, x, y), []))
        recovered_detail.append({"wafer": wafer, "x": x, "y": y, "result": detail["result"],
                                 "bin": detail["bin"], "attempt": detail["attempt"],
                                 "history": detail["history"], "evidence": detail["evidence_ids"]})

    retained = []
    for cell in preview["cells"]:
        if (cell["wafer"], cell["x"], cell["y"]) in recovered or not cell["evidence"]:
            continue
        state = "NOT_SELECTED" if cell["recommend"] == RECOVER else cell["state"]
        retained.append({"wafer": cell["wafer"], "x": cell["x"], "y": cell["y"],
                         "state": state, "reason": REASONS[state],
                         "evidence": cell["evidence_ids"]})

    wafers = []
    for summary in preview["wafers"]:
        wafer = summary["wafer"]
        recovered_here = sum(1 for item in recovered_detail if item["wafer"] == wafer)
        retained_here = sum(1 for item in retained if item["wafer"] == wafer)
        audit_wafer = next(entry for entry in audit["wafers"] if entry["wafer"] == wafer)
        wafers.append({
            "wafer": wafer,
            "edge_cells": summary["edge_cells"],
            "recovered": recovered_here,
            "retained_with_evidence": retained_here,
            "retained_without_evidence": summary["edge_cells"] - recovered_here - retained_here,
            "summary": {field: audit_wafer[field] for field in
                        ("valid", "passed", "failed", "pending", "conflict", "yield_pct")},
            "delta": audit_wafer["delta"],
            "status": audit_wafer["status"],
            "clusters": len(clusters[wafer]),
        })

    detail = {
        "selection": chosen,
        "recovered": recovered_detail,
        "retained": retained,
        "retained_counts": dict(sorted(Counter(cell["state"] for cell in retained).items())),
        "wafers": wafers,
        "summary": audit["summary"],
        "audit_status": audit["status"],
        "clusters": {wafer: len(groups) for wafer, groups in clusters.items()},
    }
    return derived, detail
