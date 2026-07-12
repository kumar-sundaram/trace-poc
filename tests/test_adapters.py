"""Embedding and LLM ports/adapters (NFR-3, FR-6)."""

import math

import pytest

from api.config import Settings
from api.resolve.adapters import (
    BedrockLLMStub,
    BedrockTitanEmbedding,
    HashEmbedding,
    MockLLMClient,
    build_embedding_client,
    build_llm_client,
)
from api.resolve.ports import Judgment, PartyDescriptor


def _descriptor(name: str, party_type: str = "INDIVIDUAL", address: str | None = None):
    return PartyDescriptor(
        party_type=party_type, normalized_name=name, normalized_address=address
    )


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class TestHashEmbedding:
    def test_deterministic_unit_vector(self):
        client = HashEmbedding(dimension=512)
        v1 = client.embed("JONATHAN SMITH 123 MAIN ST ATLANTA GA 30303")
        v2 = client.embed("JONATHAN SMITH 123 MAIN ST ATLANTA GA 30303")
        assert v1 == v2
        assert len(v1) == 512
        assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-9)

    def test_similar_strings_more_similar(self):
        client = HashEmbedding(dimension=512)
        anchor = client.embed("ROBERT CHEN AUSTIN TX")
        close = client.embed("ROBB CHEN AUSTIN TX")
        far = client.embed("PATRICIA MORRISON CHICAGO IL")
        assert _cosine(anchor, close) > _cosine(anchor, far)


class TestMockLLM:
    def test_identical_names_match_despite_addresses(self):
        # HIGH_CONNECTIVITY_NEGATIVE: same person at six addresses → one party
        result = MockLLMClient().disambiguate(
            _descriptor("PATRICIA MORRISON", address="2100 LAKEVIEW PKWY CHICAGO IL 60601"),
            _descriptor("PATRICIA MORRISON", address="5500 S SHORE DR CHICAGO IL 60637"),
        )
        assert result.judgment == Judgment.MATCH

    def test_fuzzy_variant_matches(self):
        # T3_T4_FUZZY: Robb Chen vs Robert Chen must resolve to one party
        result = MockLLMClient().disambiguate(
            _descriptor("ROBB CHEN"), _descriptor("ROBERT CHEN")
        )
        assert result.judgment == Judgment.MATCH

    def test_dissimilar_names_no_match(self):
        result = MockLLMClient().disambiguate(
            _descriptor("PATRICIA MORRISON"), _descriptor("JON TIERONE")
        )
        assert result.judgment == Judgment.NO_MATCH

    def test_cross_type_never_matches(self):
        # PARTY_TYPE_ISOLATION backstop: even similar names across types
        result = MockLLMClient().disambiguate(
            _descriptor("RIVER OAKS"),
            _descriptor("RIVER OAKS HOLDINGS LLC", party_type="ENTITY"),
        )
        assert result.judgment == Judgment.NO_MATCH

    def test_rationale_present(self):
        result = MockLLMClient().disambiguate(
            _descriptor("PATRICIA MORRISON"), _descriptor("PATRICIA MORRISON")
        )
        assert result.rationale


class TestFactoriesAndStubs:
    def test_default_config_builds_bedrock_and_mock(self):
        settings = Settings()
        assert isinstance(build_embedding_client(settings), BedrockTitanEmbedding)
        assert isinstance(build_llm_client(settings), MockLLMClient)

    def test_hash_fallback_selectable(self, monkeypatch):
        monkeypatch.setenv("TRACE_EMBEDDING__ADAPTER", "hash")
        client = build_embedding_client(Settings())
        assert isinstance(client, HashEmbedding)
        assert client.dimension == 512

    def test_unknown_adapters_rejected(self, monkeypatch):
        monkeypatch.setenv("TRACE_EMBEDDING__ADAPTER", "nope")
        with pytest.raises(ValueError):
            build_embedding_client(Settings())

    def test_llm_stub_raises(self):
        with pytest.raises(NotImplementedError):
            BedrockLLMStub().disambiguate(
                _descriptor("A"), _descriptor("B")
            )


class TestMiniLM:
    """Opt-in adapter (uv sync --group scale); skipped when not installed."""

    def test_minilm_deterministic_and_sized(self):
        pytest.importorskip("sentence_transformers")
        from api.resolve.adapters import MiniLMEmbedding

        client = MiniLMEmbedding("all-MiniLM-L6-v2", 384)
        [v1, v2] = client.embed_batch(["ROBERT CHEN AUSTIN TX"] * 2)
        assert v1 == v2
        assert len(v1) == 384
        assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-3)

    def test_minilm_dimension_mismatch_rejected(self):
        pytest.importorskip("sentence_transformers")
        from api.resolve.adapters import MiniLMEmbedding

        with pytest.raises(ValueError):
            MiniLMEmbedding("all-MiniLM-L6-v2", 512)


class TestBedrockTitanIntegration:
    """One live call — skipped when AWS credentials are absent."""

    def test_embed_deterministic_and_sized(self):
        client = build_embedding_client(Settings())
        try:
            v1 = client.embed("JONATHAN SMITH 123 MAIN ST ATLANTA GA 30303")
        except Exception as exc:  # no credentials / no model access
            pytest.skip(f"Bedrock not reachable: {exc}")
        v2 = client.embed("JONATHAN SMITH 123 MAIN ST ATLANTA GA 30303")
        assert v1 == v2
        assert len(v1) == 512
        assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-3)
