"""Meaning-based search. Turns text into number vectors so a question finds the page that says the
same thing in different words ("set up callbacks" finds the Webhook Guide).

Uses fastembed (open source, runs on the app's own computer, no extra keys). If it is not
installed or fails, the app quietly falls back to word matching.
"""
import os

import numpy as np

MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


class Embedder:
    def __init__(self, model_name=None):
        from fastembed import TextEmbedding  # imported late: may be missing
        self._m = TextEmbedding(model_name=model_name or MODEL, threads=1)  # one thread: gentler on memory

    @staticmethod
    def _norm(vecs):
        a = np.asarray(list(vecs), dtype="float32")
        n = np.linalg.norm(a, axis=1, keepdims=True)
        return a / np.where(n == 0, 1, n)

    def docs(self, texts):
        """Vectors for help-page sections, shape (len(texts), dims)."""
        return self._norm(self._m.embed(list(texts), batch_size=8))  # small batches: gentler on memory

    def query(self, text):
        """Vector for one customer question."""
        fn = getattr(self._m, "query_embed", None) or self._m.embed
        return self._norm(fn([text]))[0]


def section_text(section):
    return f"{section.get('title', '')}\n{section.get('body', '')}"[:1800]
