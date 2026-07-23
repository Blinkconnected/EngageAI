"""AI Engine endpoints. Gated by a single ``ai.use`` permission (not one
per feature — see ``docs/architecture/ai-engine.md``). Returns 503 (via
``AiNotConfiguredError``) when ``settings.ai_provider`` is ``"disabled"``,
the default.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from blinkengage.api.deps import (
    get_ai_service,
    get_conversation_service,
    get_knowledge_service,
    get_tag_repository,
    require_permission,
)
from blinkengage.api.schemas.ai import (
    ConversationSummaryResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    LanguageResponse,
    NextBestActionResponse,
    ReplySuggestionResponse,
    SentimentResponse,
    SuggestTagsResponse,
    TextRequest,
    TextResponse,
    TranslateRequest,
    TranslateResponse,
)
from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.knowledge_service import KnowledgeService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from blinkengage.infrastructure.repositories.tag_repository import TagRepository

router = APIRouter(prefix="/ai", tags=["ai"])

_HISTORY_MESSAGE_LIMIT = 50


def _format_conversation_history(messages: list[Message]) -> str:
    lines = []
    for message in messages:
        speaker = "Customer" if message.direction == MessageDirection.INBOUND else "Agent"
        if message.body:
            lines.append(f"{speaker}: {message.body}")
    return "\n".join(lines)


async def _conversation_history(
    conversation_service: ConversationService, *, company_id: UUID, conversation_id: UUID
) -> str:
    # list_messages already 404s via ConversationService.get() internally.
    messages, _ = await conversation_service.list_messages(
        company_id=company_id,
        conversation_id=conversation_id,
        offset=0,
        limit=_HISTORY_MESSAGE_LIMIT,
    )
    return _format_conversation_history(list(reversed(messages)))


@router.post(
    "/conversations/{conversation_id}/reply-suggestion", response_model=ReplySuggestionResponse
)
async def suggest_reply(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ReplySuggestionResponse:
    history = await _conversation_history(
        conversation_service, company_id=auth.company_id, conversation_id=conversation_id
    )
    suggestion = await ai_service.suggest_reply(
        company_id=auth.company_id, conversation_id=conversation_id, conversation_history=history
    )
    return ReplySuggestionResponse(suggestion=suggestion)


@router.post("/conversations/{conversation_id}/summary", response_model=ConversationSummaryResponse)
async def summarize_conversation(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationSummaryResponse:
    history = await _conversation_history(
        conversation_service, company_id=auth.company_id, conversation_id=conversation_id
    )
    summary = await ai_service.summarize_conversation(
        company_id=auth.company_id, conversation_id=conversation_id, conversation_history=history
    )
    return ConversationSummaryResponse(summary=summary)


@router.post(
    "/conversations/{conversation_id}/next-best-action", response_model=NextBestActionResponse
)
async def next_best_action(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> NextBestActionResponse:
    history = await _conversation_history(
        conversation_service, company_id=auth.company_id, conversation_id=conversation_id
    )
    result = await ai_service.suggest_next_best_action(
        company_id=auth.company_id, conversation_id=conversation_id, conversation_history=history
    )
    return NextBestActionResponse(**result)


@router.post("/translate", response_model=TranslateResponse)
async def translate(
    payload: TranslateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> TranslateResponse:
    translation = await ai_service.translate(
        company_id=auth.company_id,
        conversation_id=None,
        text=payload.text,
        target_language=payload.target_language,
    )
    return TranslateResponse(translation=translation)


@router.post("/detect-language", response_model=LanguageResponse)
async def detect_language(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> LanguageResponse:
    language = await ai_service.detect_language(
        company_id=auth.company_id, conversation_id=None, text=payload.text
    )
    return LanguageResponse(language=language)


@router.post("/sentiment", response_model=SentimentResponse)
async def analyze_sentiment(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> SentimentResponse:
    sentiment = await ai_service.analyze_sentiment(
        company_id=auth.company_id, conversation_id=None, text=payload.text
    )
    return SentimentResponse(sentiment=sentiment)


@router.post("/suggest-tags", response_model=SuggestTagsResponse)
async def suggest_tags(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    tags: Annotated[TagRepository, Depends(get_tag_repository)],
) -> SuggestTagsResponse:
    available_tags = [tag.name for tag in await tags.list_for_company(company_id=auth.company_id)]
    suggested = await ai_service.suggest_tags(
        company_id=auth.company_id,
        conversation_id=None,
        text=payload.text,
        available_tags=available_tags,
    )
    return SuggestTagsResponse(tags=suggested)


@router.post("/improve-grammar", response_model=TextResponse)
async def improve_grammar(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> TextResponse:
    result = await ai_service.improve_grammar(
        company_id=auth.company_id, conversation_id=None, text=payload.text
    )
    return TextResponse(text=result)


@router.post("/rewrite-professional", response_model=TextResponse)
async def rewrite_professionally(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> TextResponse:
    result = await ai_service.rewrite_professionally(
        company_id=auth.company_id, conversation_id=None, text=payload.text
    )
    return TextResponse(text=result)


@router.post("/knowledge-search", response_model=KnowledgeSearchResponse)
async def knowledge_search(
    payload: KnowledgeSearchRequest,
    auth: Annotated[AuthContext, Depends(require_permission("ai.use"))],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    knowledge_service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeSearchResponse:
    articles, _ = await knowledge_service.list_articles(
        company_id=auth.company_id,
        offset=0,
        limit=5,
        search=payload.query,
        category_id=None,
    )
    candidates = [(article.title, article.body) for article in articles if article.is_published]
    answer = await ai_service.answer_from_knowledge_base(
        company_id=auth.company_id,
        conversation_id=None,
        query=payload.query,
        candidate_articles=candidates,
    )
    return KnowledgeSearchResponse(answer=answer)
