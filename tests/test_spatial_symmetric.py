"""next_to와 approach는 대칭이다. 양방향을 다 내면 트리플이 두 배인데 정보는 그대로다."""
import pytest

from vtmak.spatial.interval import canonicalize
from vtmak.spatial.models import Observation


class TestCanonical:
    def test_folds_to_the_lexicographically_smaller_subject(self):
        out = canonicalize([Observation("B", "next_to", "A")], "canonical")
        assert [(o.subject, o.object) for o in out] == [("A", "B")]

    def test_deduplicates_both_orderings(self):
        out = canonicalize(
            [Observation("A", "next_to", "B"), Observation("B", "next_to", "A")],
            "canonical")
        assert len(out) == 1

    def test_leaves_asymmetric_predicates_untouched(self):
        given = [Observation("B", "in_front_of", "A"), Observation("A", "in_front_of", "B")]
        out = canonicalize(given, "canonical")
        assert len(out) == 2
        assert ("B", "A") in [(o.subject, o.object) for o in out]

    def test_preserves_evidence_when_folding(self):
        out = canonicalize([Observation("B", "next_to", "A", "x")], "canonical")
        assert out[0].evidence == "x"


class TestBoth:
    def test_emits_both_orderings(self):
        out = canonicalize([Observation("B", "next_to", "A")], "both")
        assert sorted((o.subject, o.object) for o in out) == [("A", "B"), ("B", "A")]

    def test_does_not_duplicate_when_both_are_already_present(self):
        given = [Observation("A", "next_to", "B"), Observation("B", "next_to", "A")]
        assert len(canonicalize(given, "both")) == 2

    def test_leaves_asymmetric_predicates_one_directional(self):
        out = canonicalize([Observation("S", "in_range_of", "T", "direct")], "both")
        assert [(o.subject, o.object) for o in out] == [("S", "T")]


def test_rejects_an_unknown_storage_mode():
    with pytest.raises(ValueError):
        canonicalize([Observation("A", "next_to", "B")], "sideways")
