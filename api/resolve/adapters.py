"""Adapters bound to the resolve ports (§5.2).

Default embedding: Amazon Bedrock Titan Embed v2 (decided 2026-07-12,
superseding the earlier MiniLM choice — see CLAUDE.md). The hash adapter is
the deterministic, credential-less local fallback required by NFR-3.
Default LLM: deterministic name-equality mock (FR-6) so the POC runs with no
LLM credentials; a Bedrock-hosted adapter is stubbed behind the same port.
"""

import hashlib
import json
import math
from difflib import SequenceMatcher
from functools import cached_property

from api.config import Settings
from api.resolve.ports import (
    DisambiguationResult,
    EmbeddingClient,
    Judgment,
    LLMClient,
    PartyDescriptor,
)


class BedrockTitanEmbedding(EmbeddingClient):
    """amazon.titan-embed-text-v2:0 via bedrock-runtime, normalized vectors."""

    def __init__(self, model_id: str, dimension: int, region: str) -> None:
        self._model_id = model_id
        self._dimension = dimension
        self._region = region

    @cached_property
    def _client(self):
        import boto3

        return boto3.client("bedrock-runtime", region_name=self._region)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(
                {"inputText": text, "dimensions": self._dimension, "normalize": True}
            ),
        )
        return json.loads(response["body"].read())["embedding"]


class HashEmbedding(EmbeddingClient):
    """Deterministic character-trigram hashing to a unit vector.

    No credentials, no model download (NFR-3 local default). Crude semantics,
    but stable: identical strings always embed identically, and shared
    trigrams raise cosine similarity.
    """

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        padded = f"  {text.upper()} "
        for i in range(len(padded) - 2):
            trigram = padded[i : i + 3]
            digest = hashlib.md5(trigram.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


# Mock heuristic cutoffs: near-equal names match, clearly different names
# don't, everything else stays uncertain (fail toward review, §5.3).
_NAME_MATCH_RATIO = 0.78
_NAME_NO_MATCH_RATIO = 0.50


class MockLLMClient(LLMClient):
    """Deterministic Tier-4 stand-in (FR-6): judges on name similarity alone,
    deliberately ignoring address differences — this is what lets the same
    person appear at six addresses (HIGH_CONNECTIVITY_NEGATIVE) and still
    resolve to one party."""

    def disambiguate(
        self, incoming: PartyDescriptor, candidate: PartyDescriptor
    ) -> DisambiguationResult:
        if incoming.party_type != candidate.party_type:
            return DisambiguationResult(
                Judgment.NO_MATCH, "party types differ; individuals never match entities"
            )
        # Names that differ in their digits denote distinct registrations
        # ("Generic Holdings 0 LLC" vs "Generic Holdings 1 LLC"), however
        # similar the rest of the string is.
        digits_a = sorted(t for t in incoming.normalized_name.split() if t.isdigit())
        digits_b = sorted(t for t in candidate.normalized_name.split() if t.isdigit())
        if digits_a != digits_b:
            return DisambiguationResult(
                Judgment.NO_MATCH, "numeric name tokens differ; distinct registrations"
            )
        ratio = SequenceMatcher(
            None, incoming.normalized_name, candidate.normalized_name
        ).ratio()
        if ratio >= _NAME_MATCH_RATIO:
            return DisambiguationResult(
                Judgment.MATCH, f"names near-equal (ratio {ratio:.2f}) despite address difference"
            )
        if ratio <= _NAME_NO_MATCH_RATIO:
            return DisambiguationResult(Judgment.NO_MATCH, f"names dissimilar (ratio {ratio:.2f})")
        return DisambiguationResult(
            Judgment.UNCERTAIN, f"names ambiguous (ratio {ratio:.2f}); defer to review"
        )


class BedrockLLMStub(LLMClient):
    """Placeholder proving the hosted seam exists (NFR-3); not runnable in the POC."""

    def disambiguate(
        self, incoming: PartyDescriptor, candidate: PartyDescriptor
    ) -> DisambiguationResult:
        raise NotImplementedError(
            "hosted LLM adapter is a stub in the POC; use llm.adapter=mock"
        )


def build_embedding_client(settings: Settings) -> EmbeddingClient:
    adapter = settings.embedding.adapter
    if adapter == "bedrock_titan":
        return BedrockTitanEmbedding(
            model_id=settings.embedding.model,
            dimension=settings.embedding.dimension,
            region=settings.embedding.region,
        )
    if adapter == "hash":
        return HashEmbedding(dimension=settings.embedding.dimension)
    raise ValueError(f"unknown embedding adapter: {adapter!r}")


def build_llm_client(settings: Settings) -> LLMClient:
    adapter = settings.llm.adapter
    if adapter == "mock":
        return MockLLMClient()
    if adapter == "bedrock_stub":
        return BedrockLLMStub()
    raise ValueError(f"unknown llm adapter: {adapter!r}")
