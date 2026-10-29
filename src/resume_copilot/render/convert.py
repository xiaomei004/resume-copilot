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

_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
WINDOWS_CANDIDATES = tuple(
    p
    for p in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        (os.path.join(_LOCALAPPDATA, r"Programs\LibreOffice\program\soffice.exe") if _LOCALAPPDATA else ""),
        r"C:\Program Files\LibreOffice 7\program\soffice.exe",
    )
    if p
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


def _custom_convert(docx_path: Path, pdf_path: Path, timeout: int = 180) -> bool:
    """自定义转换命令：RESUME_CONVERT_CMD 里用 {docx} / {pdf} 占位。

    有些环境（CI、只有 Word 的机器、用 pandoc 的人）没有 LibreOffice，
    这条逃生通道让页数校验仍然可用，例如：
        RESUME_CONVERT_CMD=node libreoffice-kit convert --input {docx} --output {pdf}
    """
    template = os.environ.get("RESUME_CONVERT_CMD", "").strip()
    if not template:
        return False
    cmd = template.replace("{docx}", str(docx_path)).replace("{pdf}", str(pdf_path))
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",  # Windows 默认 GBK，转换器吐 UTF-8 会炸线程
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0 and pdf_path.is_file()


def docx_to_pdf(docx_path: str | Path, soffice: str, timeout: int = 180) -> Path | None:
    """把 docx 转成同目录同名的 pdf；成功返回 pdf 路径。"""
    docx_path = Path(docx_path).resolve()
    target = docx_path.with_suffix(".pdf")
    if target.exists():
        target.unlink()
    if _custom_convert(docx_path, target):
        return target
    if not soffice:
        return None
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
            encoding="utf-8",
            errors="replace",
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
    custom = bool(os.environ.get("RESUME_CONVERT_CMD", "").strip())
    return {
        "soffice": soffice,
        "custom_converter": custom,
        "pdf_convert": bool(soffice) or custom,
        "pdf_read": _pymupdf() is not None,
        "hint": ""
        if ((soffice or custom) and _pymupdf())
        else "缺少 PDF 能力：安装 LibreOffice（或设置 RESUME_CONVERT_CMD）并安装 pymupdf，才能校验页数与出预览图。",
    }
