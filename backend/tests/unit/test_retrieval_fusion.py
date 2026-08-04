"""``domain/retrieval.py`` — Reciprocal Rank Fusion.

The property that justifies hybrid retrieval existing at all is that a
document both retrievers found should beat one either found alone. That is
the first test, and it is the one that would break if somebody "simplified"
this to a weighted score sum.
"""

from blinkengage.domain.retrieval import reciprocal_rank_fusion


def test_agreement_between_retrievers_beats_a_single_strong_hit() -> None:
    """The whole reason hybrid retrieval is better than its halves."""
    fused = reciprocal_rank_fusion(
        {
            "lexical": ["both", "lexical_only"],
            "semantic": ["semantic_only", "both"],
        }
    )

    assert fused[0][0] == "both"
    assert fused[0][2] == ("lexical", "semantic")


def test_a_document_found_by_one_retriever_still_ranks() -> None:
    """Vector-only hits are the entire point of adding semantic search —
    they are what substring matching could never find."""
    fused = reciprocal_rank_fusion({"semantic": ["only_semantic"]})

    assert [key for key, _score, _sources, _ranks in fused] == ["only_semantic"]


def test_ranks_are_reported_per_source() -> None:
    """ "Why is this here?" must be answerable from the result, not from a
    log — it is what the search response returns to the client."""
    fused = reciprocal_rank_fusion({"lexical": ["a", "b"], "semantic": ["b", "a"]})

    ranks = {key: r for key, _s, _src, r in fused}
    assert ranks["a"] == {"lexical": 1, "semantic": 2}
    assert ranks["b"] == {"lexical": 2, "semantic": 1}


def test_a_repeated_key_within_one_list_is_not_paid_for_twice() -> None:
    """A retriever returning a duplicate must not be able to buy rank with
    it — two chunks of one article collapsing to the same article is the
    real case."""
    fused = reciprocal_rank_fusion({"semantic": ["a", "a", "b"]})

    scores = {key: score for key, score, _src, _r in fused}
    assert scores["a"] == 1.0 / (60 + 1)
    assert fused[0][0] == "a"


def test_ordering_is_deterministic_for_equal_scores() -> None:
    """A retrieval that reshuffled equal results between calls would make
    every trace unreproducible and every regression test flaky."""
    first = reciprocal_rank_fusion({"lexical": ["a"], "semantic": ["b"]})
    second = reciprocal_rank_fusion({"lexical": ["a"], "semantic": ["b"]})

    assert [k for k, _s, _src, _r in first] == [k for k, _s, _src, _r in second]


def test_limit_truncates_after_ranking_not_before() -> None:
    fused = reciprocal_rank_fusion(
        {"lexical": ["x", "y", "z"], "semantic": ["z", "y", "x"]}, limit=2
    )

    assert len(fused) == 2


def test_empty_input_is_an_empty_result_not_an_error() -> None:
    assert reciprocal_rank_fusion({}) == []
    assert reciprocal_rank_fusion({"lexical": []}) == []
