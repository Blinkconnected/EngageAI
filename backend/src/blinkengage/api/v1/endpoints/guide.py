"""Serves the product guide to the application, so help lives in one place.

The guide is a Markdown file in the repository — the same one people read
on disk and in review. Serving it rather than re-typing it into the
frontend's translation catalogue is the whole point: a copy would drift,
and the copy that drifts is the one customers read.

Deliberately authenticated, unlike ``version.py``. The guide describes
screens, permissions and configuration in detail; that is reconnaissance
for anybody who is not a customer, and the public site already covers
what an evaluator needs.
"""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from blinkengage.api.deps import get_current_user, get_settings_dep
from blinkengage.core.config import Settings

router = APIRouter(tags=["guide"])


class GuideResponse(BaseModel):
    """The guide as Markdown, plus which language actually came back."""

    language: Literal["en", "ar"]
    #: ``True`` when the requested language was unavailable and English
    #: was served instead, so the interface can say so rather than
    #: leaving an Arabic reader wondering why the text is English.
    fell_back: bool
    content: str


def _read(path: Path) -> str | None:
    """The file's text, or ``None`` if it cannot be read.

    A missing guide is an operator problem, not a client one, and it must
    not raise past the caller — the language fallback below depends on
    being able to ask "is this readable?" without handling an exception
    per attempt.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


@router.get("/guide", response_model=GuideResponse)
async def get_guide(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    _user: Annotated[object, Depends(get_current_user)],
    lang: Annotated[
        Literal["en", "ar"],
        Query(description="Guide language. Falls back to English when unavailable."),
    ] = "en",
) -> GuideResponse:
    """The product guide, in the reader's language where one exists.

    Falls back to English rather than failing: somebody who opened help
    has a question now, and an English answer is worth more to them than
    an error explaining that the translation is not ready.
    """
    if lang == "ar":
        arabic = _read(Path(settings.guide_path_ar))
        if arabic is not None:
            return GuideResponse(language="ar", fell_back=False, content=arabic)

    english = _read(Path(settings.guide_path))
    if english is None:
        # Both unreadable is a deployment fault — the file is not mounted
        # — so 503 matches how a missing changelog is treated rather than
        # a 404, which would suggest the client asked for the wrong thing.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The product guide is not available on this deployment.",
        )

    return GuideResponse(language="en", fell_back=lang != "en", content=english)
