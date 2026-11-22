from datetime import datetime, timezone

from app.config import RECOVERY_VERSION, RULE_VERSION
from app.errors import ReviewError
from app.manifest import canonical, digest, fingerprint
from app.modules.edge_recovery.analysis import scan
from app.modules.edge_recovery.report import recalculate
from app.modules.intake.catalog import restore_package


def recovery_identity(run_id, base_result_sha256, selection):
    """Deterministic key: same base, rules and selection always collapse to one edition."""
    return digest(canonical([RECOVERY_VERSION, RULE_VERSION, run_id, base_result_sha256,
                             sorted(selection)]).encode())


class RecoveryService:
    def __init__(self, store):
        self.store = store

    def _base(self, run_id):
        manifest, snapshot, pinned = self.store.get(run_id)
        package = restore_package(pinned)
        key, _, _ = fingerprint(package, manifest["rule_version"])
        if (key != run_id or digest(canonical(snapshot).encode()) != manifest["result_sha256"]):
            raise ReviewError("SNAPSHOT_DAMAGED", "归档摘要不符", 409)
        return manifest, snapshot, package, pinned

    def preview(self, run_id):
        manifest, snapshot, _, _ = self._base(run_id)
        report = scan(snapshot)
        report["run_id"] = run_id
        report["sample"] = manifest["sample"]
        report["label"] = manifest["label"]
        report["lot"] = manifest["lot"]
        report["base_result_sha256"] = manifest["result_sha256"]
        report["recovery_version"] = RECOVERY_VERSION
        report["base"] = {"summary": snapshot["audit"]["summary"], "wafers": snapshot["audit"]["wafers"],
                          "clusters": {wafer: len(groups) for wafer, groups in snapshot["clusters"].items()}}
        report["editions"] = self.store.list_recoveries(run_id)
        return report

    def publish(self, run_id, selection):
        manifest, _, package, _ = self._base(run_id)
        if manifest["rule_version"] != RULE_VERSION:
            raise ReviewError("RULE_VERSION_CHANGED", "旧规则版本无法收回", 409)
        try:
            derived, detail = recalculate(package, selection)
        except (TypeError, ValueError) as exc:
            raise ReviewError("BAD_RECOVERY_SELECTION", str(exc), 422) from exc

        key = recovery_identity(run_id, manifest["result_sha256"], detail["selection"])
        result_hash = digest(canonical(derived).encode())
        record = {
            "recovery_id": key, "run_id": run_id, "sample": manifest["sample"],
            "label": manifest["label"], "lot": manifest["lot"],
            "recovery_version": RECOVERY_VERSION, "rule_version": RULE_VERSION,
            "base_result_sha256": manifest["result_sha256"],
            "selection": detail["selection"],
            "selection_sha256": digest(canonical(detail["selection"]).encode()),
            "result_sha256": result_hash,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": derived["audit"]["summary"], "status": derived["audit"]["status"],
            "recovered": len(detail["recovered"]),
            "retained": sum(1 for cell in detail["retained"] if cell["evidence"]),
            "retained_without_evidence": sum(1 for cell in detail["retained"] if not cell["evidence"]),
            "wafers": manifest["wafers"],
        }
        recorded, created = self.store.put_recovery(record, derived, detail)
        if recorded["result_sha256"] != result_hash:
            raise ReviewError("RECOVERY_DIVERGED", "同版收回结果发生变化", 409)
        return {"manifest": recorded, "reused": not created}

    def get(self, recovery_id):
        return self.store.get_recovery(recovery_id)

    def export(self, recovery_id):
        manifest, snapshot, detail = self.store.get_recovery(recovery_id)
        base_manifest, _, _, pinned = self._base(manifest["run_id"])
        if (base_manifest["result_sha256"] != manifest["base_result_sha256"]
                or digest(canonical(snapshot).encode()) != manifest["result_sha256"]
                or digest(canonical(detail["selection"]).encode()) != manifest["selection_sha256"]):
            raise ReviewError("RECOVERY_DAMAGED", "收回归档摘要不符", 409)
        return canonical({"format": "wafer-edge-recovery-v1", "manifest": manifest,
                          "base_manifest": base_manifest, "input": pinned,
                          "snapshot": snapshot, "detail": detail}).encode("utf-8")
