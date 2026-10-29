"""PDF 工具：页数与预览图（缺 pymupdf 时自动跳过）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from resume_copilot.render.convert import capabilities, find_soffice, pdf_page_count, pdf_to_png


def _has_pymupdf() -> bool:
    try:
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        try:
            import fitz  # noqa: F401
            return True
        except ImportError:
            return False


class TestPdfTools(unittest.TestCase):
    def test_capabilities_shape(self):
        caps = capabilities("")
        self.assertIn("pdf_convert", caps)
        self.assertIn("pdf_read", caps)

    def test_missing_binary_returns_none(self):
        self.assertIsNone(find_soffice("/definitely/not/here/soffice"))

    @unittest.skipUnless(_has_pymupdf(), "需要 pymupdf")
    def test_page_count_and_png(self):
        try:
            import pymupdf as mupdf
        except ImportError:
            import fitz as mupdf
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "two.pdf"
            doc = mupdf.open()
            doc.new_page()
            doc.new_page()
            doc.save(str(pdf))
            doc.close()
            self.assertEqual(pdf_page_count(pdf), 2)
            png = pdf_to_png(pdf, Path(tmp) / "p1.png", dpi=72)
            self.assertIsNotNone(png)
            self.assertTrue(Path(png).is_file())

    @unittest.skipUnless(_has_pymupdf(), "需要 pymupdf")
    def test_broken_pdf_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.pdf"
            bad.write_bytes(b"not a pdf")
            self.assertIsNone(pdf_page_count(bad))


if __name__ == "__main__":
    unittest.main()
