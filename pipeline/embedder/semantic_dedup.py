"""
semantic_dedup.py — Near-duplicate removal using sentence-transformer embeddings + FAISS.

Strategy:
  1. Embed each document (first N chars for speed).
  2. Build a FAISS flat index (exact cosine) or IVF (approximate, for >1M docs).
  3. For each doc, query k-nearest neighbors.
  4. If any neighbor has cosine similarity >= threshold, mark as duplicate,
     keeping whichever has the higher final_weight.

Memory: all-MiniLM-L6-v2 is 384-dim float32 = ~1.5KB/doc.
        1M docs ≈ 1.5GB; fine for your 8GB RAM.
        If you hit limits, switch index_type to ivf in config.
"""

from __future__ import annotations

import logging
import math
from typing import Iterator

import numpy as np

from pipeline.types import Document

log = logging.getLogger("embedder")

try:
    from sentence_transformers import SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False
    log.warning("sentence-transformers not installed; semantic dedup disabled")

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    log.warning("faiss-cpu not installed; falling back to brute-force cosine")


def _cosine_brute(matrix: np.ndarray, query: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Brute-force cosine similarity when FAISS is unavailable."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    normed = matrix / norms
    q_normed = query / (np.linalg.norm(query) + 1e-10)
    sims = normed @ q_normed
    top_k = np.argsort(sims)[::-1][:k]
    return sims[top_k], top_k


class SemanticDeduplicator:

    def __init__(self, cfg: dict):
        self._cfg       = cfg
        self._model_name = cfg.get("model", "all-MiniLM-L6-v2")
        self._batch     = cfg.get("batch_size", 256)
        self._threshold = cfg.get("similarity_threshold", 0.92)
        self._chunk     = cfg.get("chunk_size", 512)
        self._idx_type  = cfg.get("index_type", "flat")
        self._nlist     = cfg.get("ivf_nlist", 100)
        self._model     = None
        self._index     = None
        self._dim       = 0
        self._docs:     list[Document] = []
        self._embeddings: list[np.ndarray] = []
        self.stats = {"total": 0, "kept": 0, "dropped": 0}

    def _load_model(self):
        if not ST_AVAILABLE:
            raise RuntimeError("sentence-transformers not installed")
        if self._model is None:
            log.info(f"Loading sentence-transformer: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
            self._dim   = self._model.get_sentence_embedding_dimension()
            log.info(f"Embedding dim: {self._dim}")

    def _embed(self, texts: list[str]) -> np.ndarray:
        chunks = [t[:self._chunk] for t in texts]
        vecs   = self._model.encode(
            chunks,
            batch_size=self._batch,
            show_progress_bar=False,
            normalize_embeddings=True,   # L2-normalize → dot product = cosine
            convert_to_numpy=True,
        )
        return vecs.astype(np.float32)

    def _build_index(self, matrix: np.ndarray) -> "faiss.Index":
        d = matrix.shape[1]
        if self._idx_type == "ivf" and FAISS_AVAILABLE:
            nlist = min(self._nlist, max(1, matrix.shape[0] // 10))
            quantizer = faiss.IndexFlatIP(d)
            index     = faiss.IndexIVFFlat(quantizer, d, nlist, faiss.METRIC_INNER_PRODUCT)
            index.train(matrix)
            index.add(matrix)
            index.nprobe = min(10, nlist)
        elif FAISS_AVAILABLE:
            index = faiss.IndexFlatIP(d)   # inner product on L2-normed = cosine
            index.add(matrix)
        else:
            index = None
        return index

    def run(self, docs: list[Document]) -> list[Document]:
        """
        Deduplicate a list of documents.
        Returns the subset to keep.
        """
        if not docs:
            return docs

        self._load_model()
        self.stats["total"] += len(docs)

        log.info(f"Embedding {len(docs)} docs ...")
        texts  = [d.text for d in docs]
        matrix = self._embed(texts)

        log.info("Building FAISS index ...")
        index  = self._build_index(matrix)
        is_dup = [False] * len(docs)

        k = min(5, len(docs))   # check top-5 neighbors

        for i in range(len(docs)):
            if is_dup[i]:
                continue

            q = matrix[i:i+1]

            if FAISS_AVAILABLE and index is not None:
                sims, idxs = index.search(q, k + 1)
                sims  = sims[0]
                idxs  = idxs[0]
            else:
                sims, idxs = _cosine_brute(matrix, q[0], k + 1)

            for sim, j in zip(sims, idxs):
                j = int(j)
                if j <= i or j >= len(docs):
                    continue
                if float(sim) >= self._threshold:
                    # Keep the one with higher final_weight; mark the other as dup
                    if docs[i].final_weight >= docs[j].final_weight:
                        is_dup[j] = True
                        log.debug(f"DUP drop [{j}] {docs[j].url[:60]} "
                                   f"sim={sim:.3f} vs [{i}] {docs[i].url[:60]}")
                    else:
                        is_dup[i] = True
                        log.debug(f"DUP drop [{i}] {docs[i].url[:60]} "
                                   f"sim={sim:.3f} vs [{j}] {docs[j].url[:60]}")
                    break

        kept = [d for d, dup in zip(docs, is_dup) if not dup]
        dropped = len(docs) - len(kept)
        self.stats["kept"]    += len(kept)
        self.stats["dropped"] += dropped
        log.info(f"Semantic dedup: {len(docs)} → {len(kept)} (-{dropped})")
        return kept

    def stream(self, docs: Iterator[Document],
               buffer_size: int = 10000) -> Iterator[Document]:
        """
        Streaming mode: buffer N docs, dedup the batch, yield kept docs.
        Reduces memory vs loading entire corpus.
        """
        buf: list[Document] = []
        for doc in docs:
            buf.append(doc)
            if len(buf) >= buffer_size:
                yield from self.run(buf)
                buf.clear()
        if buf:
            yield from self.run(buf)

    def print_stats(self):
        s = self.stats
        t = max(s["total"], 1)
        log.info(
            f"SemanticDedup | total={s['total']} kept={s['kept']} "
            f"dropped={s['dropped']} ({s['dropped']/t*100:.1f}%)"
        )
