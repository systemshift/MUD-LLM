"""Text embedders for vector routing."""

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class HashEmbedder:
    """Offline bag-of-words embedder (hashed unigrams). Deterministic and free; for tests
    and cheap runs. It matches shared words, not meaning."""

    def __init__(self, dim: int = 512):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
                v[h % self.dim] += 1.0
            out.append(v)
        return out


class OpenAIEmbedder:
    """Semantic embeddings via the OpenAI API, cached per text."""

    def __init__(self, model: str = "text-embedding-3-small", client=None):
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        self.model = model
        self.client = client or OpenAI()
        self.cache: dict[str, list[float]] = {}
        self.tokens = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if missing:
            response = self.client.embeddings.create(model=self.model, input=missing)
            self.tokens += response.usage.total_tokens
            for text, item in zip(missing, response.data, strict=True):
                self.cache[text] = item.embedding
        return [self.cache[t] for t in texts]
