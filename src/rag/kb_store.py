"""Chroma 双 collection 封装。

设计：
- 持久化客户端 → data/chroma/
- 两个固定 collection：
    product_knowledge   ← kb_type='product'
    enterprise_knowledge ← kb_type='enterprise'
- 通过 metadata.kb_id / kb_type / file_id 实现 KB 内细粒度查询/删除
- 自定义 embedding function 复用 Embedder 单例（保证 ST / fallback 一致）
"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.rag.embedder import get_embedder

logger = logging.getLogger(__name__)


CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"

COLLECTION_MAP = {
    "product": "product_knowledge",
    "enterprise": "enterprise_knowledge",
    "experience": "experience_knowledge",  # 预留 Stage 11
}


def get_collection_for(kb_type: str) -> str:
    if kb_type not in COLLECTION_MAP:
        raise ValueError(f"未知 kb_type: {kb_type}")
    return COLLECTION_MAP[kb_type]


class _STEmbeddingFunction:
    """适配 Chroma 的 embedding function 接口（call(input) -> embeddings）。

    内部转发到全局 Embedder 单例。
    """

    def __init__(self):
        self._emb = get_embedder()

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self._emb.embed(input)

    def name(self) -> str:
        return f"dealmind-embedder-{self._emb.backend}"


_client_lock = threading.Lock()
_client_singleton: Any = None


def _get_client():
    global _client_singleton
    if _client_singleton is None:
        with _client_lock:
            if _client_singleton is None:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                CHROMA_DIR.mkdir(parents=True, exist_ok=True)
                _client_singleton = chromadb.PersistentClient(
                    path=str(CHROMA_DIR),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
                logger.info("Chroma PersistentClient ready · path=%s", CHROMA_DIR)
    return _client_singleton


class KBStore:
    """单个 KB 的视图（绑定 kb_id + kb_type → 一个 collection）。"""

    def __init__(self, kb_id: int, kb_type: str):
        self.kb_id = int(kb_id)
        self.kb_type = kb_type
        self.collection_name = get_collection_for(kb_type)
        client = _get_client()
        ef = _STEmbeddingFunction()
        self.collection = client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    # ===== 写 =====

    def add_chunks(
        self,
        *,
        file_id: int,
        filename: str,
        chunks: list[dict[str, Any]],
    ) -> int:
        """把一个文件的 chunks 批量入库。返回实际加入的 chunk 数。

        始终显式传 embeddings，避免 Chroma 在 collection 已存在时
        embedding_function 绑定失效 → 改用 default ef 导致维度漂移。
        """
        if not chunks:
            return 0
        ids: list[str] = []
        docs: list[str] = []
        metas: list[dict[str, Any]] = []
        for i, c in enumerate(chunks):
            txt = (c.get("text") or "").strip()
            if not txt:
                continue
            section = c.get("section") or ""
            extras = c.get("extras") or {}
            meta = {
                "kb_id": self.kb_id,
                "kb_type": self.kb_type,
                "file_id": int(file_id),
                "filename": filename,
                "section": section,
                "chunk_idx": i,
            }
            # Chroma metadata 只接受标量；把 extras 中标量加入
            for k, v in extras.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    meta[k] = v if v is not None else ""
            ids.append(f"f{file_id}-c{i}-{uuid.uuid4().hex[:8]}")
            docs.append(txt)
            metas.append(meta)
        if not docs:
            return 0
        emb = get_embedder()
        batch = 64
        for s in range(0, len(docs), batch):
            sub_docs = docs[s : s + batch]
            sub_embs = emb.embed(sub_docs)
            self.collection.add(
                ids=ids[s : s + batch],
                documents=sub_docs,
                metadatas=metas[s : s + batch],
                embeddings=sub_embs,
            )
        return len(docs)

    # ===== 删 =====

    def delete_by_file(self, file_id: int) -> None:
        try:
            self.collection.delete(where={"file_id": int(file_id)})
        except Exception as exc:
            logger.warning("delete_by_file (file_id=%s) failed: %s", file_id, exc)

    def delete_by_kb(self) -> None:
        try:
            self.collection.delete(where={"kb_id": self.kb_id})
        except Exception as exc:
            logger.warning("delete_by_kb (kb_id=%s) failed: %s", self.kb_id, exc)

    # ===== 查 =====

    def query(
        self,
        text: str,
        *,
        top_k: int = 3,
        scope_kb_only: bool = True,
    ) -> list[dict[str, Any]]:
        """按文本查询 top_k 个最相近的 chunks。

        scope_kb_only=True 时只在本 KB 内查；False 时整个 collection 都查
        （Stage 5 向量库管理可能用到）。

        显式 embed query 文本传 query_embeddings，避免 Chroma
        collection.embedding_function 绑定失效引起的维度不匹配。
        """
        if not text or not text.strip():
            return []
        where = {"kb_id": self.kb_id} if scope_kb_only else None
        try:
            query_emb = get_embedder().embed([text.strip()])
            res = self.collection.query(
                query_embeddings=query_emb,
                n_results=top_k,
                where=where,
            )
        except Exception as exc:
            logger.warning("query failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i, d in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            dist = float(dists[i]) if i < len(dists) and dists[i] is not None else None
            # cosine 距离 → 相似度（仅作展示）
            score = (1.0 - dist) if dist is not None else None
            out.append(
                {
                    "id": ids[i] if i < len(ids) else None,
                    "text": d,
                    "metadata": dict(meta) if meta else {},
                    "distance": dist,
                    "score": score,
                }
            )
        return out

    # ===== 统计 =====

    def count(self) -> int:
        try:
            return int(self.collection.count())
        except Exception:
            return 0


def reset_collection(kb_type: str) -> None:
    """完全清空一个 collection（Stage 5 用）。"""
    client = _get_client()
    name = get_collection_for(kb_type)
    try:
        client.delete_collection(name)
    except Exception as exc:
        logger.warning("delete_collection(%s) ignored: %s", name, exc)
    # 重新创建（保留 embedding function 绑定）
    ef = _STEmbeddingFunction()
    client.get_or_create_collection(
        name=name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
