"""渲染入口：渲染 → 转 PDF → 查页数 → 溢出就自动收紧 → 出预览图。"""

from __future__ import annotations

from pathlib import Path

from ..schemas import bullet_stats
from .convert import capabilities, docx_to_pdf, pdf_page_count, pdf_to_png
from .docx_builder import build_docx
from .theme import Theme, get_theme

__all__ = ["Theme", "get_theme", "render_resume", "capabilities"]


def render_resume(
    resume: dict,
    out_dir: str | Path,
    theme: Theme,
    *,
    stem: str = "resume",
    photo: str | Path | None = None,
    want_pdf: bool = True,
    want_png: bool = True,
    soffice: str = "",
    max_shrink_rounds: int = 6,
) -> dict:
    """渲染并尽可能保证单页。返回产物路径与诊断信息。"""
    out_dir = Path(out_dir)
    current = theme
    attempts: list[dict] = []
    pdf = png = None
    pages: int | None = None
    docx_path = out_dir / f"{stem}.docx"

    caps = capabilities(soffice)
    for round_index in range(max_shrink_rounds):
        build_docx(resume, current, docx_path, photo=photo)
        attempts.append({"round": round_index + 1, "body_pt": current.body_pt, "line": current.line})
        if not (want_pdf and caps["pdf_convert"]):
            break
        pdf = docx_to_pdf(docx_path, caps["soffice"])
        if pdf is None:
            attempts[-1]["error"] = "PDF 转换失败（soffice 返回非零或超时）"
            break
        pages = pdf_page_count(pdf) if caps["pdf_read"] else None
        if pages is None or pages <= current.max_pages:
            break
        # 溢出：收紧一档再来
        current = current.shrink(0.965)

    if pdf is not None and want_png and caps["pdf_read"]:
        png = pdf_to_png(pdf, out_dir / f"{stem}.png", dpi=140)

    result = {
        "docx": str(docx_path) if docx_path.exists() else None,
        "pdf": str(pdf) if pdf else None,
        "png": str(png) if png else None,
        "pages": pages,
        "single_page": (pages == 1) if pages is not None else None,
        "theme": current.key,
        "body_pt": current.body_pt,
        "attempts": attempts,
        "caps": caps,
        **bullet_stats(resume),
    }
    if pages is None and want_pdf:
        result["note"] = "未校验页数：缺少 LibreOffice 或 pymupdf，请自行打开 docx 确认是否一页。"
    return result
