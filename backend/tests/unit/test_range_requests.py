"""Parsing the HTTP ``Range`` header.

This is what makes dragging a video's scrubber work. The suffix-range case
is the one worth reading twice: browsers use it to find the metadata at the
*end* of an MP4 that was not written for streaming, and refusing it makes
those files silently unplayable.
"""

import pytest

from blinkengage.api.range_requests import parse_range_header

TOTAL = 1000


class TestRanges:
    def test_a_closed_range(self) -> None:
        assert parse_range_header("bytes=100-199", total_size=TOTAL) == (100, 199)

    def test_an_open_ended_range_runs_to_the_end(self) -> None:
        """What a browser sends when it starts playing without knowing how
        much it will need."""
        assert parse_range_header("bytes=500-", total_size=TOTAL) == (500, 999)

    def test_a_suffix_range_reads_the_final_bytes(self) -> None:
        """How a browser finds the moov atom at the end of a non-streaming
        MP4. Refusing this makes such files unplayable."""
        assert parse_range_header("bytes=-500", total_size=TOTAL) == (500, 999)

    def test_a_suffix_longer_than_the_file_clamps_to_the_start(self) -> None:
        assert parse_range_header("bytes=-5000", total_size=TOTAL) == (0, 999)

    def test_an_end_beyond_the_file_clamps(self) -> None:
        assert parse_range_header("bytes=900-99999", total_size=TOTAL) == (900, 999)

    def test_the_header_is_case_insensitive(self) -> None:
        assert parse_range_header("BYTES=0-9", total_size=TOTAL) == (0, 9)


class TestServingTheWholeBodyInstead:
    """Every one of these returns ``None``, which the caller serves as a
    normal 200. That is what the spec prescribes and it is the kinder
    failure: a browser that sent something odd still gets its file."""

    @pytest.mark.parametrize(
        "header",
        [
            None,
            "",
            "bytes=",
            "items=0-10",
            "bytes=abc-def",
            "bytes=10-5",
            # Starts past the end — unsatisfiable.
            "bytes=5000-",
            "bytes=-0",
            "bytes=0-10, 20-30",
        ],
    )
    def test_unusable_headers_yield_none(self, header: str | None) -> None:
        assert parse_range_header(header, total_size=TOTAL) is None

    def test_an_empty_object_yields_none(self) -> None:
        assert parse_range_header("bytes=0-", total_size=0) is None


def test_a_multipart_range_is_not_pretended_to_be_supported() -> None:
    """Legal HTTP that no browser uses for media. Returning None means the
    whole body is served, rather than a malformed single-range response
    claiming to satisfy a multipart request."""
    assert parse_range_header("bytes=0-99,200-299", total_size=TOTAL) is None
