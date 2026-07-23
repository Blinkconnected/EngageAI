from blinkengage.application.services.auth_service import slugify


def test_slugify_lowercases_and_hyphenates() -> None:
    assert slugify("Acme Corp") == "acme-corp"


def test_slugify_strips_punctuation() -> None:
    assert slugify("Acme, Inc.!!") == "acme-inc"


def test_slugify_collapses_repeated_separators() -> None:
    assert slugify("Acme   ---  Corp") == "acme-corp"


def test_slugify_falls_back_to_company_for_empty_input() -> None:
    assert slugify("!!!") == "company"
