import io
import shutil
import subprocess
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from docx import Document
from PyPDF2 import PdfReader


DOC_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def validate_document_signature(filename: str, content: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("文件扩展名为 PDF，但内容签名不匹配。")
    if suffix in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise ValueError(f"文件扩展名为 {suffix[1:].upper()}，但不是有效的 Office 文档。") from exc
        required_entry = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
        if "[Content_Types].xml" not in names or required_entry not in names:
            raise ValueError(f"文件扩展名为 {suffix[1:].upper()}，但文档结构不匹配。")
    if suffix == ".doc" and not content.startswith(DOC_SIGNATURE):
        raise ValueError("文件扩展名为 DOC，但内容签名不匹配。")
    if suffix in {".txt", ".md"} and b"\x00" in content:
        raise ValueError("文本文件包含二进制内容。")


def parse_document(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if not content:
        raise ValueError("文件为空，请重新上传。")
    validate_document_signature(filename, content)

    if suffix == ".pdf":
        return _parse_pdf(content)
    if suffix == ".docx":
        return _parse_docx(content)
    if suffix == ".doc":
        return _parse_legacy_doc(content)
    if suffix == ".xlsx":
        return _parse_xlsx(content)
    if suffix in {".txt", ".md"}:
        text = content.decode("utf-8", errors="ignore").strip()
        if not text:
            raise ValueError("文本文件未解析出内容，请检查编码或文件内容。")
        return text
    raise ValueError("仅支持 PDF、DOC、DOCX、XLSX、TXT、MD 文件。")


def _parse_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        page_texts: dict[int, str] = {}
        pages_to_ocr: list[int] = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                page_texts[index] = text
            else:
                pages_to_ocr.append(index)
    except Exception as exc:
        raise ValueError(f"PDF 解析失败：{exc}") from exc

    if pages_to_ocr:
        page_texts.update(_ocr_pdf_pages(content, pages_to_ocr))

    parsed = "".join(
        f"\n\n--- 第 {index} 页 ---\n{text}"
        for index, text in sorted(page_texts.items())
        if text
    ).strip()
    if not parsed:
        raise ValueError("PDF 未解析出文本，OCR 也未识别到有效内容，请检查扫描清晰度。")
    return parsed


@lru_cache(maxsize=1)
def _get_ocr_engine() -> Any:
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise ValueError("扫描版 PDF OCR 组件不可用，请重新安装应用后重试。") from exc
    return RapidOCR()


def _ocr_pdf_pages(content: bytes, page_numbers: list[int]) -> dict[int, str]:
    try:
        import fitz
    except ImportError as exc:
        raise ValueError("扫描版 PDF OCR 组件不可用，请重新安装应用后重试。") from exc

    try:
        document = fitz.open(stream=content, filetype="pdf")
        engine = _get_ocr_engine()
        page_texts = {}
        for page_number in page_numbers:
            page = document.load_page(page_number - 1)
            bitmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            result = engine(_pixmap_to_image(bitmap))
            text = _ocr_result_text(result)
            if text:
                page_texts[page_number] = text
        return page_texts
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"扫描版 PDF OCR 失败：{exc}") from exc


def _ocr_result_text(result: Any) -> str:
    texts = getattr(result, "txts", ())
    return "\n".join(text.strip() for text in texts if isinstance(text, str) and text.strip())


def _pixmap_to_image(bitmap: Any) -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError("扫描版 PDF OCR 组件不可用，请重新安装应用后重试。") from exc
    return np.frombuffer(bitmap.samples, dtype=np.uint8).reshape(bitmap.height, bitmap.width, bitmap.n)


def _parse_docx(content: bytes) -> str:
    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:
        raise ValueError(f"DOCX 解析失败：{exc}") from exc

    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    table_lines = []
    for table_index, table in enumerate(document.tables, start=1):
        table_lines.append(f"\n\n--- 表格 {table_index} ---")
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            table_lines.append(" | ".join(cells))

    parsed = "\n".join(paragraphs + table_lines).strip()
    if not parsed:
        raise ValueError("DOCX 未解析出文本，请检查文件内容。")
    return parsed


def _parse_xlsx(content: bytes) -> str:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValueError("XLSX 解析组件不可用，请重新安装应用后重试。") from exc

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        sheet_lines = []
        for worksheet in workbook.worksheets:
            rows = []
            for row in worksheet.iter_rows(values_only=True):
                values = [str(value).strip() if value is not None else "" for value in row]
                if any(values):
                    rows.append(" | ".join(values))
            if rows:
                sheet_lines.append(f"--- 工作表：{worksheet.title} ---\n" + "\n".join(rows))
        workbook.close()
    except Exception as exc:
        raise ValueError(f"XLSX 解析失败：{exc}") from exc

    parsed = "\n\n".join(sheet_lines).strip()
    if not parsed:
        raise ValueError("XLSX 未解析出内容，请检查工作表数据。")
    return parsed


def _parse_legacy_doc(content: bytes) -> str:
    converter = _find_legacy_doc_converter()
    if converter is None:
        raise ValueError("旧版 DOC 解析需要 LibreOffice。请安装 LibreOffice 后重试，或先转换为 DOCX。")

    try:
        with tempfile.TemporaryDirectory(prefix="bid-doc-") as temp_dir:
            source = Path(temp_dir) / "document.doc"
            source.write_bytes(content)
            if Path(converter).name == "textutil":
                result = subprocess.run(
                    [converter, "-convert", "txt", "-stdout", str(source)],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                output = result.stdout
            else:
                result = subprocess.run(
                    [converter, "--headless", "--convert-to", "txt:Text", "--outdir", temp_dir, str(source)],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                output_path = Path(temp_dir) / "document.txt"
                output = output_path.read_bytes() if output_path.exists() else b""
    except subprocess.TimeoutExpired as exc:
        raise ValueError("DOC 解析超时，请先转换为 DOCX 后重试。") from exc

    text = output.decode("utf-8", errors="ignore").strip()
    if result.returncode != 0 or not text:
        raise ValueError("DOC 未解析出内容，请检查文件是否受保护或先转换为 DOCX。")
    return text


def _find_legacy_doc_converter() -> str | None:
    for command in ("soffice", "libreoffice", "textutil"):
        path = shutil.which(command)
        if path:
            return path
    return None
