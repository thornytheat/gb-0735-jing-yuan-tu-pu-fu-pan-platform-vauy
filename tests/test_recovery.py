import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.errors import ReviewError
from app.manifest import canonical, digest
from app.modules.edge_recovery.analysis import RETAIN, inspect_rows, scan
from app.modules.edge_recovery.report import recalculate
from app.modules.edge_recovery.service import RecoveryService
from app.modules.intake.catalog import load_sample
from app.modules.runs.pipeline import calculate


def row(line, attempt, result, bin_code, note="", source="p.csv"):
    return {"id": f"{source}:{line}", "source": source, "line": line, "end_line": line,
            "bucket": "candidate", "code": None,
            "fields": {"wafer": "W-01", "x": "0", "y": "0", "attempt": str(attempt),
                       "result": result, "bin": str(bin_code), "note": note}}


def state(rows):
    return inspect_rows(rows)


def test_transient_contact_failure_recovers_but_repeated_failure_is_retained():
    contact = state([row(2, 1, "FAIL", 5), row(3, 2, "PASS", 1, "夹具重压")])
    assert (contact["state"], contact["recommend"]) == ("RECOVERED", "RECOVER")
    assert [step["result"] for step in contact["history"]] == ["FAIL", "PASS"]

    repeated = state([row(2, 1, "FAIL", 5), row(3, 2, "FAIL", 5), row(4, 3, "FAIL", 6)])
    assert (repeated["state"], repeated["recommend"]) == ("REPEATED_EDGE_FAILURE", RETAIN)
    assert repeated["result"] == "FAIL"


def test_single_edge_failure_conflict_missing_and_bad_values_are_all_retained():
    cases = {
        "EDGE_FAILURE": [row(2, 1, "FAIL", 5)],
        "EDGE_CONFLICT": [row(2, 2, "PASS", 1), row(3, 2, "FAIL", 5)],
        "NO_EDGE_EVIDENCE": [],
        "BAD_EDGE_MEASUREMENT": [row(2, "x", "PASS", 1)],
    }
    for expected, rows in cases.items():
        detail = state(rows)
        assert (detail["state"], detail["recommend"]) == (expected, RETAIN), expected


def test_missing_later_value_does_not_erase_earlier_failure():
    detail = state([row(2, 1, "FAIL", 5), row(3, 2, "N/A", "-")])
    assert (detail["state"], detail["recommend"], detail["attempt"]) == ("EDGE_FAILURE", RETAIN, 1)


def test_preview_lists_only_the_evidence_backed_edge_die(snapshot):
    preview = scan(snapshot)
    assert preview["wafers"] == [
        {"wafer": "W-07", "edge_cells": 118, "recoverable": 1, "with_evidence": 1},
        {"wafer": "W-08", "edge_cells": 61, "recoverable": 0, "with_evidence": 0},
    ]
    assert preview["recoverable"] == [["W-07", 12, 0]]
    die = next(cell for cell in preview["cells"] if cell["evidence"])
    assert (die["state"], die["recommend"]) == ("RECOVERED", "RECOVER")
    assert die["evidence_ids"] == ["probe-a.csv:549"]


def test_publish_recomputes_clusters_yield_and_ledger_delta_without_mutating_base(client, run_base):
    base = client.get(run_base + "/yield").json()
    before = client.get(run_base).json()
    response = client.post(run_base + "/recovery", json={})
    assert response.status_code == 201
    manifest = response.json()["manifest"]
    assert manifest["selection"] == [["W-07", 12, 0]]

    conclusion = client.get(run_base + f'/recovery/{manifest["recovery_id"]}').json()
    assert conclusion["summary"] == {"conflict": 2, "coverage_pct": "95.91", "failed": 33,
                                     "passed": 505, "pending": 23, "valid": 563, "yield_pct": "89.70"}
    first = conclusion["detail"]["wafers"][0]
    assert first["summary"]["valid"] == 314 and first["delta"]["valid"] == 1
    assert first["clusters"] == conclusion["clusters"]["W-07"] == 7
    assert conclusion["detail"]["recovered"][0]["evidence"] == ["probe-a.csv:549"]
    assert {item["id"] for item in conclusion["rows"]} == {"probe-a.csv:549"}

    assert client.get(run_base).json() == before
    assert client.get(run_base + "/yield").json()["summary"] == base["summary"]
    assert client.get(run_base + "/mask/W-07").json()["counts"]["EDGE_EXCLUSION"] == 118
    derived_mask = client.get(run_base + f'/recovery/{manifest["recovery_id"]}/mask/W-07').json()
    assert derived_mask["counts"] == {"ACTIVE": 314, "OUTSIDE_DISC": 184,
                                      "EDGE_EXCLUSION": 117, "NOTCH_VOID": 10}


def test_repeating_the_same_recovery_never_creates_a_second_conclusion(client, run_base):
    first = client.post(run_base + "/recovery", json={"selection": [["W-07", 12, 0]]})
    repeat = client.post(run_base + "/recovery", json={"selection": [["W-07", 12, 0]]})
    assert first.status_code == 201 and repeat.status_code == 200
    assert repeat.json() == {"manifest": first.json()["manifest"], "reused": True}
    editions = client.get(run_base + "/recovery").json()["editions"]
    assert [item["recovery_id"] for item in editions] == [first.json()["manifest"]["recovery_id"]]


def test_parallel_publish_commits_one_edition(client, run_base):
    run_id = run_base.rsplit("/", 1)[1]
    service = client.app.state.recoveries
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.publish(run_id, [["W-07", 12, 0]]), range(4)))
    assert sum(not result["reused"] for result in results) == 1
    assert len(service.store.list_recoveries(run_id)) == 1


def test_retained_and_non_edge_selections_are_rejected(client, run_base):
    cases = [
        ([["W-07", 0, 0]], "不在边缘保留带"),
        ([["W-07", 12, 0], ["W-07", 0, 0]], "不在边缘保留带"),
        ([["W-99", 0, 0]], "不在边缘保留带"),
    ]
    for selection, message in cases:
        response = client.post(run_base + "/recovery", json={"selection": selection})
        assert (response.status_code, response.json()["code"]) == (422, "BAD_RECOVERY_SELECTION")
        assert message in response.json()["message"]
    assert client.get(run_base + "/recovery").json()["editions"] == []


def test_retain_recommendation_blocks_a_failing_edge_die(package):
    # A second and third failure on the edge band is evidence of real edge loss:
    # it may never be swept into the valid population by a recovery run.
    from app.modules.intake.contract import InputPackage
    files = dict(package.files)
    files["probe-a.csv"] = package.files["probe-a.csv"].rstrip(b"\r\n") + (
        "\r\nW-07,252,480,2,FAIL,7,二次失效\r\nW-07,252,480,3,FAIL,7,三次失效\r\n".encode("utf-8"))
    spec = package.spec.model_copy(update={"sources": [
        package.spec.sources[0].model_copy(update={"records": 556}), package.spec.sources[1]]})
    revised = InputPackage(spec, files)
    _, detail = recalculate(revised, [])
    assert detail["selection"] == []
    retained = {(cell["wafer"], cell["x"], cell["y"]): cell for cell in detail["retained"]}
    assert retained[("W-07", 12, 0)]["state"] == "REPEATED_EDGE_FAILURE"
    with pytest.raises(ValueError):
        recalculate(revised, [["W-07", 12, 0]])


def test_api_rejects_recovering_a_repeatedly_failing_edge_die(client, package):
    from app.modules.intake.contract import InputPackage
    from app.modules.runs.service import RunService
    files = dict(package.files)
    files["probe-a.csv"] = package.files["probe-a.csv"].rstrip(b"\r\n") + (
        "\r\nW-07,252,480,2,FAIL,7,二次失效\r\nW-07,252,480,3,FAIL,7,三次失效\r\n".encode("utf-8"))
    spec = package.spec.model_copy(update={"sources": [
        package.spec.sources[0].model_copy(update={"records": 556}), package.spec.sources[1]]})
    service = RunService(client.app.state.runs.store, loader=lambda _: InputPackage(spec, files))
    run_id = service.start("revised")["manifest"]["run_id"]
    preview = client.get(f"/api/runs/{run_id}/recovery").json()
    assert preview["recoverable"] == []
    retained = next(cell for cell in preview["cells"] if cell["evidence"])
    assert retained["state"] == "REPEATED_EDGE_FAILURE"
    response = client.post(f"/api/runs/{run_id}/recovery", json={"selection": [["W-07", 12, 0]]})
    assert (response.status_code, response.json()["code"]) == (422, "BAD_RECOVERY_SELECTION")
    assert client.get(f"/api/runs/{run_id}/recovery").json()["editions"] == []


def test_interrupted_publish_keeps_previous_edition_and_original_rows(client, run_base):
    first = client.post(run_base + "/recovery", json={"selection": [["W-07", 12, 0]]}).json()["manifest"]
    store = client.app.state.recoveries.store
    with store.connect() as connection:
        connection.execute("CREATE TRIGGER fail_recovery AFTER INSERT ON wafer_recoveries "
                           "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    failed = client.post(run_base + "/recovery", json={"selection": []})
    assert (failed.status_code, failed.json()["code"]) == (503, "STORAGE_ERROR")
    editions = client.get(run_base + "/recovery").json()["editions"]
    assert [item["recovery_id"] for item in editions] == [first["recovery_id"]]
    assert client.get(run_base + f'/recovery/{first["recovery_id"]}').status_code == 200

    with store.connect() as connection:
        connection.execute("DROP TRIGGER fail_recovery")
    retry = client.post(run_base + "/recovery", json={"selection": [["W-07", 12, 0]]})
    assert retry.status_code == 200 and retry.json()["reused"] is True


def test_export_replays_from_pinned_bytes_and_is_reproducible(client, run_base, package):
    manifest = client.post(run_base + "/recovery", json={}).json()["manifest"]
    url = run_base + f'/recovery/{manifest["recovery_id"]}/export'
    response = client.get(url)
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["format"] == "wafer-edge-recovery-v1"
    assert bundle["manifest"]["result_sha256"] == digest(canonical(bundle["snapshot"]).encode())
    assert bundle["manifest"]["base_result_sha256"] == digest(canonical(calculate(package)).encode())
    assert bundle["base_manifest"]["result_sha256"] == bundle["manifest"]["base_result_sha256"]
    assert client.get(url).content == response.content
    assert client.get(run_base + "/export").json()["manifest"]["result_sha256"] == bundle["manifest"]["base_result_sha256"]


def test_damaged_recovery_archive_is_reported(client, run_base):
    manifest = client.post(run_base + "/recovery", json={}).json()["manifest"]
    store = client.app.state.recoveries.store
    with store.connect() as connection:
        connection.execute("UPDATE wafer_recoveries SET detail = ? WHERE recovery_id = ?",
                           (canonical({"selection": [["W-07", 9, 9]]}), manifest["recovery_id"]))
    response = client.get(run_base + f'/recovery/{manifest["recovery_id"]}/export')
    assert (response.status_code, response.json()["code"]) == (409, "RECOVERY_DAMAGED")


def test_edge_page_exposes_publish_controls(client, run_base):
    page = client.get("/edge")
    assert page.status_code == 200 and "<h1>边缘收回</h1>" in page.text
    assert all(control in page.text for control in ('id="recovery-publish"', 'id="recovery-candidates"',
                                                    'id="recovery-retained"', 'id="recovery-editions"'))


def test_recovery_service_rejects_changed_base_snapshot(client, run_base):
    run_id = run_base.rsplit("/", 1)[1]
    store = client.app.state.recoveries.store
    with store.connect() as connection:
        connection.execute("UPDATE wafer_runs SET snapshot = ? WHERE run_id = ?", ("{}", run_id))
    with pytest.raises(ReviewError) as error:
        RecoveryService(store).publish(run_id, None)
    assert error.value.code == "SNAPSHOT_DAMAGED"
