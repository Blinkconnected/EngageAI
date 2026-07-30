"""What an attachment is, and whether it can be shown inline.

Being wrong towards "just offer a download" costs a click. Being wrong the
other way renders a broken element where the customer's photo should be,
which is worse: it looks like the file is corrupt, and an agent tells the
customer to send it again.
"""

import pytest

from blinkengage.domain.media import (
    DEFAULT_VIDEO_ASPECT_RATIO,
    MediaKind,
    has_measurable_dimensions,
    is_inline_renderable,
    kind_for,
    may_need_fallback,
)


class TestClassification:
    @pytest.mark.parametrize(
        ("content_type", "expected"),
        [
            ("image/jpeg", MediaKind.IMAGE),
            ("image/png", MediaKind.IMAGE),
            ("image/webp", MediaKind.IMAGE),
            ("video/mp4", MediaKind.VIDEO),
            # What an iPhone sends.
            ("video/quicktime", MediaKind.VIDEO),
            ("audio/mpeg", MediaKind.AUDIO),
            ("application/pdf", MediaKind.DOCUMENT),
            ("application/vnd.ms-excel", MediaKind.FILE),
            ("application/octet-stream", MediaKind.FILE),
        ],
    )
    def test_kinds(self, content_type: str, expected: MediaKind) -> None:
        assert kind_for(content_type) is expected

    def test_svg_is_a_file_not_an_image(self) -> None:
        """An SVG is an image by MIME type and an executable document in
        practice. Rendering a customer-supplied one inline is a
        script-injection surface, so it is deliberately downloadable only."""
        assert kind_for("image/svg+xml") is MediaKind.FILE
        assert not is_inline_renderable("image/svg+xml")

    def test_content_type_parameters_are_ignored(self) -> None:
        """WhatsApp voice notes arrive as `audio/ogg; codecs=opus`. A lookup
        that missed on the parameter would offer a download for something
        the browser plays perfectly well."""
        assert kind_for("audio/ogg; codecs=opus") is MediaKind.AUDIO

    def test_case_is_ignored(self) -> None:
        assert kind_for("IMAGE/JPEG") is MediaKind.IMAGE

    def test_an_unknown_type_is_never_shown_inline(self) -> None:
        assert not is_inline_renderable("application/x-whatever")


class TestFallbacks:
    def test_heic_is_an_image_but_flagged(self) -> None:
        """HEIC only decodes natively on Apple platforms. Classified as an
        image so it gets the right icon and lightbox affordance, flagged so
        the UI offers "open in a new tab" rather than showing a broken
        image and blaming the customer."""
        assert kind_for("image/heic") is MediaKind.IMAGE
        assert may_need_fallback("image/heic")

    def test_common_web_formats_need_no_fallback(self) -> None:
        for content_type in ("image/jpeg", "image/png", "image/webp"):
            assert not may_need_fallback(content_type), content_type


class TestDimensions:
    def test_only_images_are_measurable(self) -> None:
        """Video dimensions need a demuxer this deployment does not carry,
        so video reserves a default aspect ratio instead of pretending."""
        assert has_measurable_dimensions("image/png")
        assert not has_measurable_dimensions("video/mp4")
        assert not has_measurable_dimensions("audio/mpeg")
        assert not has_measurable_dimensions("application/pdf")

    def test_the_video_default_is_landscape_sixteen_nine(self) -> None:
        assert pytest.approx(16 / 9) == DEFAULT_VIDEO_ASPECT_RATIO
