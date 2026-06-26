"""RAG 业务模块：embedder / parsers / kb_store / seed。

对外主入口：
- Embedder: 嵌入模型单例
- parse_file: 多格式文档解析 + 切片
- KBStore: Chroma 双 collection 封装
- seed_default_kbs: 启动时预填两个训练 KB
"""

from src.rag.embedder import Embedder, get_embedder
from src.rag.kb_store import COLLECTION_MAP, KBStore, get_collection_for
from src.rag.parsers import ParserError, chunk_text, parse_file
from src.rag.seed import seed_default_kbs, start_indexer_thread

__all__ = [
    "Embedder",
    "get_embedder",
    "KBStore",
    "COLLECTION_MAP",
    "get_collection_for",
    "parse_file",
    "chunk_text",
    "ParserError",
    "seed_default_kbs",
    "start_indexer_thread",
]
