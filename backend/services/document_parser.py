import io
from pathlib import Path

from docx import Document
from PyPDF2 import PdfReader


def parse_document(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if not content:
        raise ValueError("文件为空，请重新上传。")

    if suffix == ".pdf":
        return _parse_pdf(content)
    if suffix == ".docx":
        return _parse_docx(content)
    if suffix in {".txt", ".md"}:
        text = content.decode("utf-8", errors="ignore").strip()
        if not text:
            raise ValueError("文本文件未解析出内容，请检查编码或文件内容。")
        return text
    raise ValueError("仅支持 PDF、DOCX、TXT、MD 文件。旧版 .doc 请先转换为 .docx。")


def _parse_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(f"\n\n--- 第 {index} 页 ---\n{text.strip()}")
        parsed = "".join(pages).strip()
    except Exception as exc:
        raise ValueError(f"PDF 解析失败：{exc}") from exc

    if not parsed:
        raise ValueError("PDF 未解析出文本，可能是扫描件或受保护文件，请先 OCR 后再上传。")
    return parsed


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
