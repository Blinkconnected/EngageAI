"""``domain/chunking.py`` — pure, so tested directly with no database.

Chunk boundaries decide retrieval quality more than model choice does, so
these assert the *rules*, not just that something comes back.
"""

from blinkengage.domain.chunking import (
    chunk_article,
    embeddable_text,
)


def test_a_short_article_is_one_chunk() -> None:
    chunks = chunk_article(title="Refunds", body="We refund within 14 days.")

    assert len(chunks) == 1
    assert chunks[0].ordinal == 0
    assert "14 days" in chunks[0].text


def test_the_title_is_carried_on_every_chunk() -> None:
    """A chunk is retrieved alone and must stand alone. Without the title
    in its heading path, "within 14 days of receipt" is about nothing."""
    body = "\n\n".join(f"Paragraph {n}. " + "word " * 200 for n in range(4))

    chunks = chunk_article(title="Refund policy", body=body)

    assert len(chunks) > 1
    assert all(chunk.heading_path is not None for chunk in chunks)
    assert all("Refund policy" in str(chunk.heading_path) for chunk in chunks)


def test_markdown_headings_become_the_heading_path() -> None:
    body = "# Refunds\n\nWe refund within 14 days.\n\n## Late delivery\n\nSame window applies."

    chunks = chunk_article(title="Help", body=body)

    paths = [chunk.heading_path for chunk in chunks]
    assert any(path == "Help > Refunds" for path in paths)
    assert any(path == "Help > Refunds > Late delivery" for path in paths)


def test_chunks_respect_the_character_bound() -> None:
    body = "\n\n".join("sentence. " * 60 for _ in range(10))

    chunks = chunk_article(title="Manual", body=body, max_chars=500, overlap_chars=50)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 500 for chunk in chunks)


def test_a_single_oversized_sentence_is_hard_split_rather_than_dropped() -> None:
    """The last-resort branch. Losing content silently would be worse than
    an inelegant boundary."""
    body = "x" * 3000

    chunks = chunk_article(title="Weird", body=body, max_chars=500, overlap_chars=50)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 500 for chunk in chunks)
    assert sum(len(chunk.text) for chunk in chunks) >= 3000


def test_ordinals_are_contiguous_from_zero() -> None:
    """The unique constraint is (article_id, ordinal), and the re-index
    matches old to new chunks by ordinal — a gap would orphan a chunk and
    leave its vector behind."""
    body = "\n\n".join(f"Paragraph {n}. " + "word " * 100 for n in range(6))

    chunks = chunk_article(title="Manual", body=body, max_chars=400, overlap_chars=40)

    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_an_empty_article_produces_no_chunks() -> None:
    """A zero-content vector is close to every query — the single worst row
    a retrieval index can hold."""
    assert chunk_article(title="   ", body="\n\n   \n") == []


def test_a_title_with_no_body_is_still_indexed() -> None:
    """An FAQ entry whose question is the whole article is a real shape."""
    chunks = chunk_article(title="Do you ship to Aqaba?", body="")

    assert len(chunks) == 1
    assert "Aqaba" in chunks[0].text


def test_arabic_prose_splits_on_arabic_sentence_terminators() -> None:
    """Arabic uses ؟ for a question mark. Without it in the terminator set,
    Arabic text is one unbroken run that only ever hard-splits."""
    sentence = "نحن نقدم استرداد الأموال خلال أربعة عشر يوما من الاستلام؟ "
    body = sentence * 40

    chunks = chunk_article(title="سياسة الاسترداد", body=body, max_chars=400, overlap_chars=40)

    assert len(chunks) > 1
    # A hard split would leave chunks at exactly the bound; sentence
    # splitting leaves them short of it.
    assert any(len(chunk.text) < 400 for chunk in chunks)


def test_a_trailing_runt_is_merged_rather_than_left_alone() -> None:
    body = "word " * 300 + "\n\nThanks."

    chunks = chunk_article(title="Guide", body=body, max_chars=2000, overlap_chars=100)

    assert all(len(chunk.text) > 20 for chunk in chunks)
    assert "Thanks." in chunks[-1].text


def test_embeddable_text_includes_the_heading_path() -> None:
    """What is hashed and what is sent to the provider must be one string;
    if they diverge, every chunk looks changed on every re-index."""
    chunks = chunk_article(title="Refunds", body="Within 14 days.")

    text = embeddable_text(chunks[0])

    assert text.startswith("Refunds")
    assert "14 days" in text
