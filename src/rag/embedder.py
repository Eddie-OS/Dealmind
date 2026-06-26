"""嵌入模型单例。

默认使用 BAAI/bge-small-zh-v1.5（约 100MB），中文小模型，CPU 也跑得动。
首次加载会从 HuggingFace 下载并缓存到 ~/.cache/huggingface/hub/。

兜底策略：
- HF 下载失败 / 模型不存在 → fallback 到 Chroma 默认 embedder
  （chromadb 内置的 onnx all-MiniLM-L6-v2，对中文效果一般但保证不阻断启动）

环境变量：
- DM_EMBED_MODEL: 自定义模型名（默认 BAAI/bge-small-zh-v1.5）
- HF_ENDPOINT:    HuggingFace 镜像，如 https://hf-mirror.com（国内推荐）
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


_FALLBACK_MODEL = "BAAI/bge-small-zh-v1.5"


def _resolve_default_model() -> str:
    """**调用时**而非 import 时读 DM_EMBED_MODEL。

    避免与 .env 加载时序冲突：当 ``embedder`` 模块被早期 import 时，
    若直接在模块级取 ``os.getenv``，.env 通常还没加载，会拿到 None →
    fallback 到硬编码默认，导致 .env 里写的模型完全失效。
    """
    return os.getenv("DM_EMBED_MODEL", _FALLBACK_MODEL)


class Embedder:
    """嵌入模型包装，对外只暴露 embed(texts) -> list[list[float]]。"""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or _resolve_default_model()
        self.backend: str = "pending"  # 'sentence_transformers' | 'chroma_default' | 'pending'
        self._model: Any = None
        self._chroma_ef: Any = None
        self._dim: int | None = None
        self._error: str | None = None

    def _try_load_st(self) -> bool:
        try:
            from sentence_transformers import SentenceTransformer

            logger.info("loading sentence-transformers model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
            # 探测维度
            probe = self._model.encode(["probe"], normalize_embeddings=True)
            self._dim = len(probe[0]) if len(probe) else None
            self.backend = "sentence_transformers"
            logger.info("embedder ready · backend=st · dim=%s", self._dim)
            return True
        except Exception as exc:  # 包括 OSError / ImportError / 网络下载失败
            self._error = f"sentence_transformers load failed: {exc}"
            logger.warning(self._error)
            return False

    def _try_load_chroma_default(self) -> bool:
        try:
            from chromadb.utils import embedding_functions

            self._chroma_ef = embedding_functions.DefaultEmbeddingFunction()
            # Chroma default 是 all-MiniLM-L6-v2，dim=384
            probe = self._chroma_ef(["probe"])
            self._dim = len(probe[0]) if len(probe) else None
            self.backend = "chroma_default"
            logger.warning(
                "embedder fallback → chroma_default (dim=%s). 中文检索效果会下降，"
                "建议设置 HF_ENDPOINT=https://hf-mirror.com 重启后用 bge 模型。",
                self._dim,
            )
            return True
        except Exception as exc:
            self._error = (self._error or "") + f" | chroma_default load failed: {exc}"
            logger.error(self._error)
            return False

    def ensure_loaded(self) -> None:
        if self.backend != "pending":
            return
        if self._try_load_st():
            return
        if self._try_load_chroma_default():
            return
        raise RuntimeError(
            f"无法加载任何 embedding 模型。最近错误: {self._error}"
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.ensure_loaded()
        if not texts:
            return []
        if self.backend == "sentence_transformers":
            vectors = self._model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return [list(map(float, v)) for v in vectors]
        # chroma_default
        return [list(map(float, v)) for v in self._chroma_ef(texts)]

    @property
    def dim(self) -> int | None:
        return self._dim

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model_name if self.backend == "sentence_transformers" else "all-MiniLM-L6-v2",
            "dim": self._dim,
            "hf_endpoint": os.getenv("HF_ENDPOINT"),
            "error": self._error,
        }


_INSTANCE: Embedder | None = None
_LOCK = threading.Lock()


def get_embedder() -> Embedder:
    """全局单例，线程安全。"""
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = Embedder()
    return _INSTANCE
