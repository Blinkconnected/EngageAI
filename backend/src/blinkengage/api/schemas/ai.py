from pydantic import BaseModel, Field


class ReplySuggestionResponse(BaseModel):
    suggestion: str


class ConversationSummaryResponse(BaseModel):
    summary: str


class NextBestActionResponse(BaseModel):
    action: str
    reason: str


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1)
    target_language: str = Field(..., min_length=1, max_length=100)


class TranslateResponse(BaseModel):
    translation: str


class TextRequest(BaseModel):
    """The shared shape for the single-text-in AI endpoints (sentiment,
    language detection, grammar, professional rewrite, tag suggestion)."""

    text: str = Field(..., min_length=1)


class LanguageResponse(BaseModel):
    language: str


class SentimentResponse(BaseModel):
    sentiment: str


class SuggestTagsResponse(BaseModel):
    tags: list[str]


class TextResponse(BaseModel):
    text: str


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


class KnowledgeSearchResponse(BaseModel):
    answer: str
