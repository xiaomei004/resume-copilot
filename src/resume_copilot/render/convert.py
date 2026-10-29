"""格式转换与页数探测。

DOCX -> PDF 用 LibreOffice 无头模式（soffice）；页数与预览图用 pymupdf。
两个依赖都是可选的：缺哪个就跳过哪一步，并在结果里写清楚为什么跳过。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

WINDOWS_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
MAC_CANDIDATES = ("/Applications/LibreOffice.app/Contents/MacOS/soffice",)


def find_soffice(hint: str = "") -> str | None:
    """按 hint -> PATH -> 常见安装路径 的顺序找 soffice。"""
    for candidate in (hint, os.environ.get("RESUME_SOFFICE", "")):
        if candidate and Path(candidate).is_file():
            return candidate
    which = shutil.which("soffice") or shutil.which("libreoffice")
    if which:
        return which
    for candidate in (*WINDOWS_CANDIDATES, *MAC_CANDIDATES):
        if Path(candidate).is_file():
            return candidate
    return None


def _pymupdf():
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except ImportError:
        try:
            import fitz  # type: ignore

            return fitz
        except ImportError:
            return None


def docx_to_pdf(docx_path: str | Path, soffice: str, timeout: int = 180) -> Path | None:
    """把 docx 转成同目录同名的 pdf；成功返回 pdf 路径。"""
    docx_path = Path(docx_path).resolve()
    target = docx_path.with_suffix(".pdf")
    if target.exists():
        target.unlink()
    profile = Path(tempfile.gettempdir()) / f"resume-copilot-{uuid.uuid4().hex[:8]}"
    cmd = [
        soffice,
        "--headless",
        "--norestore",
        "--nolockcheck",
        f"-env:UserInstallation=file:///{profile.as_posix()}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(docx_path.parent),
        str(docx_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if proc.returncode != 0 and not target.exists():
        return None
    return target if target.exists() else None


def pdf_page_count(pdf_path: str | Path) -> int | None:
    module = _pymupdf()
    if module is None:
        return None
    try:
        with module.open(str(pdf_path)) as doc:
            return doc.page_count
    except Exception:
        return None


def pdf_to_png(pdf_path: str | Path, png_path: str | Path, dpi: int = 140, page: int = 0) -> Path | None:
    module = _pymupdf()
    if module is None:
        return None
    try:
        with module.open(str(pdf_path)) as doc:
            if page >= doc.page_count:
                return None
            pix = doc[page].get_pixmap(dpi=dpi)
            out = Path(png_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(out))
            return out
    except Exception:
        return None


def capabilities(soffice_hint: str = "") -> dict:
    soffice = find_soffice(soffice_hint)
    return {
        "soffice": soffice,
        "pdf_convert": bool(soffice),
        "pdf_read": _pymupdf() is not None,
        "hint": "" if (soffice and _pymupdf()) else "缺少 PDF 能力：安装 LibreOffice 与 pymupdf 可自动校验页数与出预览图。",
    }
