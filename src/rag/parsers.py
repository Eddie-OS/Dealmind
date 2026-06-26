"""文档解析 + 切片。

对外主入口：
- parse_file(path) -> list[ChunkDict]
- chunk_text(text, chunk_size=400, overlap=80) -> list[str]

ChunkDict 结构：
    {
        "text": str,            # 切片正文
        "section": str,         # 来源段落（用于 metadata，可读）
        "extras": dict,         # 额外 metadata（xlsx 行有 column_names 等）
    }

每种格式的切片策略：
- .txt/.md  : 按 "^## " 二级标题切；标题段过大再走滑动窗口
- .pdf      : 每页一段（section="Page {n}"），过大走滑窗
- .docx     : 每 5 段合并为一段（section="Paragraph {i}"）
- .pptx     : 每幻灯片一段（section="Slide {n}: {title}"）
- .xlsx     : 每 sheet 每行一段（section="{sheet} Row {n}"），header 进 metadata
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, TypedDict, Union

logger = logging.getLogger(__name__)


CHUNK_SIZE = 400
CHUNK_OVERLAP = 80
MAX_CHUNKS_PER_FILE = 5000  # 防止异常大文件爆炸性切片

PathLike = Union[str, Path]


class ChunkDict(TypedDict, total=False):
    text: str
    section: str
    extras: dict[str, Any]


class ParserError(RuntimeError):
    """解析失败。"""


def _to_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """简单的滑动窗口切片。

    优先按段落 / 句末标点保留语义；过短文本不切。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + chunk_size, n)
        # 在 [i, end] 内向后找最近的标点收尾，避免硬切到字中间
        if end < n:
            tail = text.rfind("。", i, end)
            if tail < i + chunk_size // 2:
                tail = text.rfind("\n", i, end)
            if tail >= i + chunk_size // 2:
                end = tail + 1
        chunk = text[i:end].strip()
        if chunk:
            out.append(chunk)
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return out


def _section_to_chunks(section_title: str, body: str) -> list[ChunkDict]:
    """把 (section_title, body) 切成多个 ChunkDict（共享 section）。"""
    chunks: list[ChunkDict] = []
    for piece in chunk_text(body):
        chunks.append({"text": piece, "section": section_title, "extras": {}})
    return chunks


# ============================================================
# .txt / .md
# ============================================================

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _parse_text(path: Path) -> list[ChunkDict]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore").strip()
    if not text:
        return []
    headings = list(_HEADING_RE.finditer(text))
    if not headings:
        return _section_to_chunks(path.stem, text)

    out: list[ChunkDict] = []
    sections: list[tuple[str, int, int]] = []  # (title, start, end)
    for i, m in enumerate(headings):
        title = m.group(2).strip()
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        sections.append((title, start, end))

    # 把开头的文本（heading 之前）当作"前言"段
    prefix = text[: headings[0].start()].strip()
    if prefix:
        out.extend(_section_to_chunks(f"{path.stem} · 前言", prefix))

    for title, start, end in sections:
        body = text[start:end].strip()
        if not body:
            continue
        out.extend(_section_to_chunks(title, body))
    return out


# ============================================================
# .pdf
# ============================================================


def _parse_pdf(path: Path) -> list[ChunkDict]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ParserError("pypdf 未安装") from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise ParserError(f"PDF 打开失败 {path.name}: {exc}") from exc

    out: list[ChunkDict] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception as exc:
            logger.warning("PDF page %d extract failed: %s", idx, exc)
            continue
        if not text:
            continue
        out.extend(_section_to_chunks(f"Page {idx}", text))
        if len(out) >= MAX_CHUNKS_PER_FILE:
            logger.warning("PDF %s 达到 chunk 上限 %d，截断", path.name, MAX_CHUNKS_PER_FILE)
            break
    return out


# ============================================================
# .docx
# ============================================================

DOCX_GROUP_SIZE = 5


def _docx_iter_blocks(doc):
    """按文档真实顺序产出 (kind, obj)：段落与表格交错。

    python-docx 默认 doc.paragraphs / doc.tables 分别遍历，会丢失二者的
    相对顺序，且 doc.paragraphs **完全不含表格内文字**。这里直接遍历
    body 的 XML 子节点，保证顺序，并把表格一并纳入。
    """
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield "p", Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield "tbl", Table(child, doc)


def _docx_table_to_text(table) -> str:
    """把 Word 表格渲染成可读文本：每行 `单元格 | 单元格`，多行单元格用 / 连接。"""
    lines: list[str] = []
    for row in table.rows:
        cells = [(c.text or "").strip().replace("\n", " / ") for c in row.cells]
        # 去掉整行空白；保留有内容的行
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _parse_docx(path: Path) -> list[ChunkDict]:
    try:
        import docx
    except ImportError as exc:
        raise ParserError("python-docx 未安装") from exc

    try:
        doc = docx.Document(str(path))
    except Exception as exc:
        raise ParserError(f"docx 打开失败 {path.name}: {exc}") from exc

    out: list[ChunkDict] = []
    cur_section = path.stem
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            out.extend(_section_to_chunks(cur_section, body))
        buf.clear()

    for kind, obj in _docx_iter_blocks(doc):
        if kind == "p":
            text = (obj.text or "").strip()
            if not text:
                continue
            style = (obj.style.name if obj.style else "") or ""
            # 标题样式（Heading 1-9 / 自定义 *heading*）→ 开启新 section
            is_heading = "heading" in style.lower()
            if is_heading:
                flush()
                cur_section = text[:80]
                buf.append(text)
            else:
                buf.append(text)
        elif kind == "tbl":
            tbl_text = _docx_table_to_text(obj)
            if tbl_text:
                buf.append(tbl_text)
        if len(out) >= MAX_CHUNKS_PER_FILE:
            break

    flush()
    return out


# ============================================================
# .pptx
# ============================================================


def _parse_pptx(path: Path) -> list[ChunkDict]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise ParserError("python-pptx 未安装") from exc

    try:
        prs = Presentation(str(path))
    except Exception as exc:
        raise ParserError(f"pptx 打开失败 {path.name}: {exc}") from exc

    out: list[ChunkDict] = []
    for idx, slide in enumerate(prs.slides, start=1):
        title = ""
        texts: list[str] = []
        for shape in slide.shapes:
            # 标题
            if shape.has_text_frame and shape == slide.shapes.title:
                title = (shape.text_frame.text or "").strip()
            elif getattr(shape, "has_text_frame", False):
                t = (shape.text_frame.text or "").strip()
                if t:
                    texts.append(t)
            # 表格
            if getattr(shape, "has_table", False):
                try:
                    for row in shape.table.rows:
                        cells = [c.text.strip() for c in row.cells if c.text]
                        if cells:
                            texts.append(" | ".join(cells))
                except Exception:
                    pass

        # title 可能在非 title 占位中——再补一次
        if not title:
            title = f"Slide {idx}"

        body_parts = []
        if title:
            body_parts.append(title)
        body_parts.extend(texts)
        body = "\n".join(body_parts).strip()
        if not body:
            continue
        section = f"Slide {idx}: {title[:50]}" if title else f"Slide {idx}"
        out.extend(_section_to_chunks(section, body))
        if len(out) >= MAX_CHUNKS_PER_FILE:
            break
    return out


# ============================================================
# .xlsx
# ============================================================


def _parse_xlsx(path: Path) -> list[ChunkDict]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ParserError("openpyxl 未安装") from exc

    try:
        wb = load_workbook(str(path), data_only=True, read_only=True)
    except Exception as exc:
        raise ParserError(f"xlsx 打开失败 {path.name}: {exc}") from exc

    out: list[ChunkDict] = []
    for sheet in wb.worksheets:
        sheet_name = sheet.title
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            continue
        column_names = [
            (str(c).strip() if c is not None else f"col_{i}")
            for i, c in enumerate(header_row)
        ]
        for ri, row in enumerate(rows_iter, start=2):
            if row is None:
                continue
            cells: list[str] = []
            for col_name, val in zip(column_names, row):
                if val is None:
                    continue
                s = str(val).strip()
                if not s:
                    continue
                cells.append(f"{col_name}: {s}")
            if not cells:
                continue
            text = "\n".join(cells)
            section = f"{sheet_name} Row {ri}"
            # xlsx 行天然短，通常一行一个 chunk；只在异常大行时才切
            for piece in chunk_text(text):
                out.append(
                    {
                        "text": piece,
                        "section": section,
                        "extras": {
                            "sheet": sheet_name,
                            "row": ri,
                            "column_names": ",".join(column_names),
                        },
                    }
                )
            if len(out) >= MAX_CHUNKS_PER_FILE:
                logger.warning(
                    "xlsx %s 达到 chunk 上限 %d，截断", path.name, MAX_CHUNKS_PER_FILE
                )
                wb.close()
                return out
    wb.close()
    return out


# ============================================================
# 分派入口
# ============================================================


_DISPATCH = {
    ".txt": _parse_text,
    ".md": _parse_text,
    ".pdf": _parse_pdf,
    ".docx": _parse_docx,
    ".pptx": _parse_pptx,
    ".xlsx": _parse_xlsx,
}

SUPPORTED_SUFFIXES = tuple(_DISPATCH.keys())


def parse_file(path: PathLike) -> list[ChunkDict]:
    p = _to_path(path)
    if not p.exists():
        raise ParserError(f"文件不存在: {p}")
    if not p.is_file():
        raise ParserError(f"非文件路径: {p}")
    suffix = p.suffix.lower()
    fn = _DISPATCH.get(suffix)
    if fn is None:
        raise ParserError(
            f"不支持的格式 {suffix}（{p.name}）。支持: {', '.join(SUPPORTED_SUFFIXES)}"
        )
    chunks = fn(p)
    return chunks
