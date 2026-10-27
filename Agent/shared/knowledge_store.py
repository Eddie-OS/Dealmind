"""零依赖的关键词检索，顶替 Chroma 向量库。

放弃向量检索的代价与收益：
    代价 —— 没有语义泛化，"续航不行"检索不到"电池容量"这种同义表达。
    收益 —— 不需要 embedding 模型（省一次 100MB+ 下载与常驻内存），
            Agent/ 目录可以整个拷走离线跑，检索结果完全可解释。

打分口径（三项加权，都归一化到 0-1 后相加）：
    1. 中文二元组重合度 —— 中文没有空格，按字符 bigram 近似分词
    2. ASCII 词重合度   —— 型号/英文术语（Pura X、120Hz、SoC）
    3. 数字重合度       —— 价格、参数这类最该被精确召回的内容，单独加权

命中结果的形状与上游 KBStore.query 完全一致（text / metadata / distance），
所以 vendored agents._fetch_kb_hits 与 _format_hits_for_prompt 不需要任何改动。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_CJK = r"\u4e00-\u9fff"
_ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-\+\.]{1,}")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_CJK_RE = re.compile(f"[{_CJK}]+")

# 中文里高频但不携带检索信号的字，计入 bigram 会稀释真正的匹配
_STOP_BIGRAMS = {"的的", "了的", "我们", "你们", "这个", "那个", "可以", "什么", "怎么"}

_CHUNK_TARGET = 420      # 单个 chunk 的目标字符数
_CHUNK_MAX = 700         # 硬上限，超了强制切
_SUPPORTED_SUFFIXES = {".md", ".txt", ".markdown"}


def _cjk_bigrams(text: str) -> set[str]:
    out: set[str] = set()
    for run in _CJK_RE.findall(text):
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg not in _STOP_BIGRAMS:
                out.add(bg)
        if len(run) == 1:
            out.add(run)
    return out


def _ascii_words(text: str) -> set[str]:
    return {w.lower() for w in _ASCII_WORD_RE.findall(text)}


def _numbers(text: str) -> set[str]:
    return set(_NUM_RE.findall(text))


@dataclass
class _Chunk:
    text: str
    filename: str
    section: str
    bigrams: set[str]
    words: set[str]
    nums: set[str]


def _split_sections(raw: str) -> Iterable[tuple[str, str]]:
    """按 markdown 标题切段，返回 (section_title, body)。无标题时整篇一段。"""
    lines = raw.splitlines()
    section = ""
    buf: list[str] = []
    for line in lines:
        if line.lstrip().startswith("#"):
            if any(s.strip() for s in buf):
                yield section, "\n".join(buf)
            section = line.lstrip("#").strip()
            buf = []
        else:
            buf.append(line)
    if any(s.strip() for s in buf):
        yield section, "\n".join(buf)


def _split_chunks(body: str) -> Iterable[str]:
    """段落优先，累积到目标长度就切；单段超长时硬切。"""
    buf = ""
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        while len(para) > _CHUNK_MAX:
            yield para[:_CHUNK_MAX]
            para = para[_CHUNK_MAX:]
        if len(buf) + len(para) + 1 > _CHUNK_TARGET and buf:
            yield buf.strip()
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf.strip():
        yield buf.strip()


class KeywordKnowledgeStore:
    """对一个目录下的 md/txt 建立内存索引。首次 query 时惰性加载。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._chunks: list[_Chunk] | None = None

    def _load(self) -> list[_Chunk]:
        if self._chunks is not None:
            return self._chunks
        chunks: list[_Chunk] = []
        if self.root.is_dir():
            for path in sorted(self.root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                    continue
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                rel = str(path.relative_to(self.root)).replace("\\", "/")
                for section, body in _split_sections(raw):
                    for text in _split_chunks(body):
                        chunks.append(
                            _Chunk(
                                text=text,
                                filename=rel,
                                section=section,
                                bigrams=_cjk_bigrams(text),
                                words=_ascii_words(text),
                                nums=_numbers(text),
                            )
                        )
        self._chunks = chunks
        return chunks

    @property
    def chunk_count(self) -> int:
        return len(self._load())

    def query(
        self, query: str, top_k: int = 3, scope_kb_only: bool = True
    ) -> list[dict[str, Any]]:
        """签名与上游 KBStore.query 对齐；scope_kb_only 在文件后端下无意义，保留占位。"""
        del scope_kb_only
        chunks = self._load()
        if not chunks or not (query or "").strip():
            return []

        q_bg, q_w, q_n = _cjk_bigrams(query), _ascii_words(query), _numbers(query)
        if not (q_bg or q_w or q_n):
            return []

        scored: list[tuple[float, _Chunk]] = []
        for c in chunks:
            score = 0.0
            if q_bg:
                score += 1.0 * len(q_bg & c.bigrams) / len(q_bg)
            if q_w:
                score += 1.2 * len(q_w & c.words) / len(q_w)
            if q_n:
                score += 1.5 * len(q_n & c.nums) / len(q_n)
            if score > 0:
                scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        max_score = max((s for s, _ in scored[:1]), default=0.0) or 1.0

        hits: list[dict[str, Any]] = []
        for score, c in scored[: max(1, top_k)]:
            hits.append(
                {
                    "text": c.text,
                    # distance 语义与向量库一致：越小越相关
                    "distance": round(1.0 - min(score / max_score, 1.0), 4),
                    "metadata": {
                        "filename": c.filename,
                        "section": c.section,
                        "retriever": "keyword",
                    },
                }
            )
        return hits
