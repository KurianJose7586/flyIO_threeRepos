"""
ChromaDB storage layer.

Embeddings: sentence-transformers "all-MiniLM-L6-v2" — free, offline,
no API key, accurate enough for a RAG demo. Chroma's built-in
SentenceTransformerEmbeddingFunction handles loading the model and
embedding both inserted documents and search queries consistently.

Each chunk gets a stable id (hash of source_url + chunk_index) plus a
content hash in its metadata, so re-running the crawler only re-embeds
chunks whose text actually changed — cheap incremental updates instead
of recomputing every embedding on every automated run.
"""
import hashlib

import chromadb
from chromadb.utils import embedding_functions

from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME, EMBEDDING_MODEL_NAME

_client = None
_collection = None


def _stable_id(chunk: dict) -> str:
    key = f"{chunk['source_url']}::{chunk['chunk_index']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL_NAME
        )
        _collection = _client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            embedding_function=embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def upsert_chunks(chunks: list) -> int:
    """
    Upserts chunks, skipping any whose content hasn't changed since the
    last run (checked via existing metadata). Returns the number of
    chunks actually (re-)embedded.
    """
    if not chunks:
        return 0

    collection = get_collection()

    ids = [_stable_id(c) for c in chunks]
    existing = collection.get(ids=ids, include=["metadatas"])
    existing_hashes = {
        eid: (meta or {}).get("content_hash")
        for eid, meta in zip(existing.get("ids", []), existing.get("metadatas", []))
    }

    new_ids, documents, metadatas = [], [], []
    for chunk_id, chunk in zip(ids, chunks):
        h = _content_hash(chunk["content_text"])
        if existing_hashes.get(chunk_id) == h:
            continue  # unchanged since last crawl — skip re-embedding
        new_ids.append(chunk_id)
        documents.append(chunk["content_text"])
        metadatas.append({
            "source_url": chunk["source_url"],
            "page_title": chunk["page_title"],
            "section_path": chunk.get("section_path", ""),
            "chunk_index": chunk["chunk_index"],
            "content_html": chunk["content_html"][:4000],
            "content_hash": h,
        })

    if new_ids:
        collection.upsert(ids=new_ids, documents=documents, metadatas=metadatas)

    return len(new_ids)


def query(text: str, n_results: int = 5, source_filter: str | None = None) -> dict:
    """Semantic search over stored chunks. Optional source_filter matches
    an exact source_url."""
    collection = get_collection()
    where = {"source_url": source_filter} if source_filter else None
    return collection.query(query_texts=[text], n_results=n_results, where=where)


def count() -> int:
    return get_collection().count()
