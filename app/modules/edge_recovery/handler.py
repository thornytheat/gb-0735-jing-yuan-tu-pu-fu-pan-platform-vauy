from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.dependencies import Archive
from app.errors import ReviewError

router = APIRouter(prefix="/api/runs/{run_id}/recovery")


class RecoveryRequest(BaseModel):
    selection: list[tuple[str, int, int]] | None = None


def recovery_service(request: Request):
    return request.app.state.recoveries


Service = Annotated[object, Depends(recovery_service)]


def _recovery(service, run_id, recovery_id):
    manifest, snapshot, detail = service.get(recovery_id)
    if manifest["run_id"] != run_id:
        raise ReviewError("RECOVERY_NOT_FOUND", "边缘收回结论未找到", 404)
    return manifest, snapshot, detail


def _cited(detail):
    cited = {row_id for cell in detail["recovered"] for row_id in cell["evidence"]}
    cited.update(row_id for cell in detail["retained"] for row_id in cell["evidence"])
    return cited


@router.get("")
def preview(archive: Archive, service: Service):
    return service.preview(archive[0]["run_id"])


@router.post("", status_code=201)
def publish(run_id: str, service: Service, response: Response, request: RecoveryRequest | None = None):
    result = service.publish(run_id, request.selection if request else None)
    if result["reused"]:
        response.status_code = 200
    return result


@router.get("/{recovery_id}")
def conclusion(run_id: str, recovery_id: str, service: Service):
    manifest, snapshot, detail = _recovery(service, run_id, recovery_id)
    return {"manifest": manifest, "detail": detail,
            "summary": snapshot["audit"]["summary"], "audit": snapshot["audit"],
            "clusters": {wafer: len(groups) for wafer, groups in snapshot["clusters"].items()},
            "rows": [row for row in snapshot["rows"] if row["id"] in _cited(detail)]}


@router.get("/{recovery_id}/yield")
def reconciliation(run_id: str, recovery_id: str, service: Service):
    _, snapshot, _ = _recovery(service, run_id, recovery_id)
    return {**snapshot["audit"], "reasons": snapshot["reasons"]}


@router.get("/{recovery_id}/clusters/{wafer}")
def clusters(run_id: str, recovery_id: str, service: Service, wafer: str):
    _, snapshot, _ = _recovery(service, run_id, recovery_id)
    return snapshot["clusters"].get(wafer, [])


@router.get("/{recovery_id}/mask/{wafer}")
def mask(run_id: str, recovery_id: str, service: Service, wafer: str):
    _, snapshot, _ = _recovery(service, run_id, recovery_id)
    return snapshot["masks"].get(wafer)


@router.get("/{recovery_id}/export")
def export(run_id: str, recovery_id: str, service: Service):
    _recovery(service, run_id, recovery_id)
    filename = f"edge-recovery-{recovery_id[:16]}.json"
    return Response(service.export(recovery_id), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
