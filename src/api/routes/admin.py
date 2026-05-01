import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PIPELINE_DIR = PROJECT_ROOT / "src" / "pipeline"


async def require_admin_key(request: Request, x_admin_key: str = Header(default="")) -> None:
    expected = request.app.state.admin_key
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin key not configured on server")
    if x_admin_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid X-Admin-Key")


class IngestRequest(BaseModel):
    run_ingest: bool = True
    run_embed: bool = True


class IngestResponse(BaseModel):
    ok: bool
    steps: list[dict]


def _run(script: str) -> dict:
    proc = subprocess.run(
        [sys.executable, script],
        cwd=str(PIPELINE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "script": script,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


@router.post("/ingest", response_model=IngestResponse, dependencies=[Depends(require_admin_key)])
async def ingest(payload: IngestRequest, request: Request) -> IngestResponse:
    steps: list[dict] = []
    ok = True

    if payload.run_ingest:
        step = _run("ingest.py")
        steps.append(step)
        if step["returncode"] != 0:
            ok = False

    if ok and payload.run_embed:
        step = _run("embed_and_store.py")
        steps.append(step)
        if step["returncode"] != 0:
            ok = False

    # Refresh the collection handle so new data is immediately visible
    try:
        collection = request.app.state.chroma_client.get_collection(
            name="hust_regulations_v2",
            embedding_function=request.app.state.embedding_fn,
        )
        request.app.state.collection = collection
    except Exception as e:
        steps.append({"script": "reload_collection", "returncode": 1, "error": str(e)})
        ok = False

    return IngestResponse(ok=ok, steps=steps)


@router.get("/stats", dependencies=[Depends(require_admin_key)])
async def stats(request: Request) -> dict:
    col = request.app.state.collection
    return {"collection": "hust_regulations_v2", "count": col.count()}
