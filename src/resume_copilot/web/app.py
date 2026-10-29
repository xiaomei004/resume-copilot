"""Web 界面：上传材料 → 跑流水线 → 下载简历与速查卡。

刻意做得轻：单页 HTML + 轮询状态，不用前端构建链。
启动：`resume-copilot serve`，或 `uvicorn resume_copilot.web.app:app --reload`
"""

from __future__ import annotations

import json
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import __version__, agents
from ..config import Config
from ..ingest import read_any
from ..pipeline import prepare_inputs, run
from ..render import capabilities

app = FastAPI(title="resume-copilot", description="多 Agent 简历优化流水线", version=__version__)

STATIC_DIR = Path(__file__).parent / "static"
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()

ARTIFACT_KEYS = {
    "pdf": ("resume", ".pdf", "application/pdf"),
    "docx": ("resume", ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "png": ("resume", ".png", "image/png"),
    "card": ("interview_card", ".md", "text/markdown; charset=utf-8"),
    "report": ("report", ".md", "text/markdown; charset=utf-8"),
}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = STATIC_DIR / "index.html"
    if not page.is_file():  # pragma: no cover
        raise HTTPException(500, "缺少 web/static/index.html")
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict:
    cfg = Config.from_env()
    caps = capabilities(cfg.soffice)
    return {
        "version": __version__,
        "model": cfg.model,
        "has_key": cfg.has_key,
        "research": cfg.research_ready,
        "pdf": caps["pdf_convert"] and caps["pdf_read"],
        "agents": [spec.describe() for spec in agents.ALL_AGENTS],
    }


@app.post("/api/jobs")
async def create_job(
    jd: list[UploadFile] = File(default=[]),
    resume: list[UploadFile] = File(default=[]),
    info: list[UploadFile] = File(default=[]),
    photo: UploadFile | None = File(default=None),
    role: str = Form(default=""),
    theme: str = Form(default=""),
    rounds: int = Form(default=2),
    research: bool = Form(default=True),
) -> JSONResponse:
    if not jd:
        raise HTTPException(400, "至少上传一份 JD")
    if not resume and not info:
        raise HTTPException(400, "至少上传一份旧简历或补充信息")

    cfg = Config.from_env()
    if not cfg.has_key:
        raise HTTPException(
            400,
            "未配置 OPENAI_API_KEY。请复制 .env.example 为 .env 并填写 key；"
            "只想先看流程可以走命令行：resume-copilot run --mock --dir examples/materials",
        )

    job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    workdir = Path("./out") / f"job-{job_id}"
    upload_dir = workdir / "inputs"
    upload_dir.mkdir(parents=True, exist_ok=True)

    jd_paths: list[Path] = []
    resume_paths: list[Path] = []
    info_paths: list[Path] = []
    for file_list, bucket in ((jd, jd_paths), (resume, resume_paths), (info, info_paths)):
        for f in file_list:
            if not f.filename:
                continue
            target = upload_dir / Path(f.filename).name
            target.write_bytes(await f.read())
            bucket.append(target)

    photo_path = None
    if photo is not None and photo.filename:
        photo_path = upload_dir / Path(photo.filename).name
        photo_path.write_bytes(await photo.read())

    sources_jd = [read_any(p, "jd") for p in jd_paths]
    sources_resume = [read_any(p, "resume") for p in resume_paths]
    sources_info = [read_any(p, "info") for p in info_paths]
    inputs = prepare_inputs(sources_jd, sources_resume, sources_info, role)

    cfg.out_dir = Path("./out")
    cfg.max_revision_rounds = max(0, min(rounds, 4))
    cfg.research_enabled = research

    with LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "steps": [],
            "root": str(workdir),
            "error": "",
            "artifacts": {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    def worker() -> None:
        def on_step(record: dict) -> None:
            with LOCK:
                JOBS[job_id]["steps"].append(record)

        try:
            result = run(
                cfg,
                inputs,
                out_root=workdir.parent,
                photo=photo_path,
                theme_name=theme or None,
                on_step=on_step,
            )
            manifest = result["manifest"]
            with LOCK:
                JOBS[job_id].update(
                    status=manifest["status"],
                    error=manifest.get("error", ""),
                    artifacts=manifest.get("artifacts", {}),
                    metrics=manifest.get("metrics", {}),
                    usage=manifest.get("usage", {}),
                )
        except Exception as exc:  # noqa: BLE001
            with LOCK:
                JOBS[job_id].update(status="failed", error=f"{type(exc).__name__}: {exc}")
            traceback.print_exc()

    threading.Thread(target=worker, daemon=True).start()
    return JSONResponse({"id": job_id, "status": "queued"}, status_code=202)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    payload = dict(job)
    root = Path(job["root"])
    manifest_path = root / "manifest.json"
    if manifest_path.is_file() and payload["status"] in {"queued", "running"}:
        payload["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"] = {key: f"/api/jobs/{job_id}/file/{key}" for key in ARTIFACT_KEYS if root.joinpath(f"resume.{key}").is_file() or root.joinpath(f"{ARTIFACT_KEYS[key][0]}.md").is_file()}
    return payload


@app.get("/api/jobs/{job_id}/file/{kind}")
def job_file(job_id: str, kind: str) -> FileResponse:
    with LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if kind not in ARTIFACT_KEYS:
        raise HTTPException(400, "未知文件类型")
    stem, suffix, media = ARTIFACT_KEYS[kind]
    path = Path(job["root"]) / f"{stem}{suffix}"
    if not path.is_file():
        raise HTTPException(404, f"尚未生成 {kind}")
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    with LOCK:
        return sorted(
            (
                {"id": j["id"], "status": j["status"], "created_at": j["created_at"], "title": (j.get("metrics") or {}).get("title")}
                for j in JOBS.values()
            ),
            key=lambda x: x["created_at"],
            reverse=True,
        )
