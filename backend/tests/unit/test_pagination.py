from blinkengage.api.schemas.pagination import PageParams


def test_first_page_has_zero_offset() -> None:
    assert PageParams(page=1, page_size=20).offset == 0


def test_offset_scales_with_page_number() -> None:
    assert PageParams(page=3, page_size=20).offset == 40


def test_offset_respects_custom_page_size() -> None:
    assert PageParams(page=2, page_size=5).offset == 5
