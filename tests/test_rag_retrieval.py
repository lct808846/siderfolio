"""Acceptance-failure regressions; these cases remain pending execution."""

from types import SimpleNamespace

import pytest

from astroagent.errors import ServiceError
from astroagent.rag_retrieval import QueryVectorCache, query_cache_key, requires_literal_anchor
from astroagent.rag_schemas import RetrievalTrace
from astroagent.rag_service import RagService


@pytest.mark.parametrize(
    "question",
    [
        "unknownterm",
        "NGC999999",
        "NGC 999999",
        '"unlisted-id"',
        "'unknownword'?",
        "１２３４５",
        "???",
    ],
)
def test_underspecified_literal_requires_anchor(question):
    assert requires_literal_anchor(question)


@pytest.mark.parametrize(
    "question",
    ["双星团银河潮汐作用", "dynamical fate of binary star clusters", "What are quasars?"],
)
def test_natural_context_remains_eligible_for_semantic_only_retrieval(question):
    assert not requires_literal_anchor(question)


def test_cache_expires_without_extending_retention_on_reads():
    now = [0.0]
    cache = QueryVectorCache(2, 5, lambda: now[0])
    cache.put("one", [1.0, 0.0])
    now[0] = 4
    assert cache.get("one") == [1.0, 0.0]
    now[0] = 5
    assert cache.get("one") is None


def test_cache_evicts_least_recently_used_and_copies_vectors():
    cache = QueryVectorCache(2)
    source = [1.0, 0.0]
    cache.put("one", source)
    source[0] = 0.0
    cache.put("two", [0.0, 1.0])
    found = cache.get("one")
    assert found == [1.0, 0.0]
    found[0] = 0.0
    cache.put("three", [0.5, 0.5])
    assert cache.get("two") is None
    assert cache.get("one") == [1.0, 0.0]


def test_cache_key_separates_project_model_dimension_and_question():
    key = query_cache_key("project-a", "a" * 64, 384, "private question")
    assert key != query_cache_key("project-b", "a" * 64, 384, "private question")
    assert key != query_cache_key("project-a", "b" * 64, 384, "private question")
    assert key != query_cache_key("project-a", "a" * 64, 768, "private question")
    assert key != query_cache_key("project-a", "a" * 64, 384, "different question")


def test_cache_can_be_disabled():
    cache = QueryVectorCache(capacity=0)
    cache.put("one", [1.0, 0.0])
    assert cache.get("one") is None


def test_cache_cannot_hide_missing_or_changed_model():
    calls = []
    model = SimpleNamespace(sha="a" * 64, missing=False)

    def identity():
        if model.missing:
            raise ServiceError(503, "rag_model_identity_invalid", "missing")
        return model.sha

    def encode(texts):
        calls.append(texts)
        return [[1.0, 0.0]]

    service = object.__new__(RagService)
    service.settings = SimpleNamespace(rag_dimension=2)
    service.embedder = SimpleNamespace(identity=identity, encode=encode)
    service.query_vectors = QueryVectorCache()
    assert service._query_vector("a", "question")[1] is False
    assert service._query_vector("a", "question")[1] is True
    assert len(calls) == 1
    model.missing = True
    with pytest.raises(ServiceError):
        service._query_vector("a", "question")
    model.missing, model.sha = False, "b" * 64
    assert service._query_vector("a", "question")[1] is False
    assert len(calls) == 2


def test_legacy_trace_does_not_claim_new_admission_or_cache():
    old = RetrievalTrace(max_cosine_distance=0.65)
    assert old.version == "pg-rrf-v1"
    assert old.embedding_cache_hit is None
