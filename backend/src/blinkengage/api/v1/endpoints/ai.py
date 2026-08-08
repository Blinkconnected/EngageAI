"""AI Engine endpoints. Gated by a single ``ai.use`` permission (not one
per feature — see ``docs/architecture/ai-engine.md``) plus a per-user
rate limit (``enforce_ai_rate_limit`` — every AI call has a real external
cost, see ``docs/security/hardening.md``). Returns 503 (via
``AiNotConfiguredError``) when ``settings.ai_provider`` is ``"disabled"``,
the default.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from blinkengage.api.deps import (
    enforce_ai_rate_limit,
    get_ai_service,
    get_conversation_service,
    get_faq_retrieval_service,
    get_knowledge_retrieval_service,
    get_tag_repository,
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
from blinkengage.application.services.faq_retrieval_service import FaqRetrievalService
from blinkengage.application.services.knowledge_retrieval_service import (
    KnowledgeRetrievalService,
)
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
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ReplySuggestionResponse:
    history = await _conversation_history(
        conversation_service, company_id=auth.company_id, conversation_id=conversation_id
    )
    suggestion = await ai_service.suggest_reply(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        conversation_history=history,
        actor_user_id=auth.user_id,
    )
    return ReplySuggestionResponse(suggestion=suggestion)


@router.post("/conversations/{conversation_id}/summary", response_model=ConversationSummaryResponse)
async def summarize_conversation(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationSummaryResponse:
    history = await _conversation_history(
        conversation_service, company_id=auth.company_id, conversation_id=conversation_id
    )
    summary = await ai_service.summarize_conversation(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        conversation_history=history,
        actor_user_id=auth.user_id,
    )
    return ConversationSummaryResponse(summary=summary)


@router.post(
    "/conversations/{conversation_id}/next-best-action", response_model=NextBestActionResponse
)
async def next_best_action(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> NextBestActionResponse:
    history = await _conversation_history(
        conversation_service, company_id=auth.company_id, conversation_id=conversation_id
    )
    result = await ai_service.suggest_next_best_action(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        conversation_history=history,
        actor_user_id=auth.user_id,
    )
    return NextBestActionResponse(**result)


@router.post("/translate", response_model=TranslateResponse)
async def translate(
    payload: TranslateRequest,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> TranslateResponse:
    translation = await ai_service.translate(
        company_id=auth.company_id,
        conversation_id=None,
        text=payload.text,
        target_language=payload.target_language,
        actor_user_id=auth.user_id,
    )
    return TranslateResponse(translation=translation)


@router.post("/detect-language", response_model=LanguageResponse)
async def detect_language(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> LanguageResponse:
    language = await ai_service.detect_language(
        company_id=auth.company_id,
        conversation_id=None,
        text=payload.text,
        actor_user_id=auth.user_id,
    )
    return LanguageResponse(language=language)


@router.post("/sentiment", response_model=SentimentResponse)
async def analyze_sentiment(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> SentimentResponse:
    sentiment = await ai_service.analyze_sentiment(
        company_id=auth.company_id,
        conversation_id=None,
        text=payload.text,
        actor_user_id=auth.user_id,
    )
    return SentimentResponse(sentiment=sentiment)


@router.post("/suggest-tags", response_model=SuggestTagsResponse)
async def suggest_tags(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    tags: Annotated[TagRepository, Depends(get_tag_repository)],
) -> SuggestTagsResponse:
    available_tags = [tag.name for tag in await tags.list_for_company(company_id=auth.company_id)]
    suggested = await ai_service.suggest_tags(
        company_id=auth.company_id,
        conversation_id=None,
        text=payload.text,
        available_tags=available_tags,
        actor_user_id=auth.user_id,
    )
    return SuggestTagsResponse(tags=suggested)


@router.post("/improve-grammar", response_model=TextResponse)
async def improve_grammar(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> TextResponse:
    result = await ai_service.improve_grammar(
        company_id=auth.company_id,
        conversation_id=None,
        text=payload.text,
        actor_user_id=auth.user_id,
    )
    return TextResponse(text=result)


@router.post("/rewrite-professional", response_model=TextResponse)
async def rewrite_professionally(
    payload: TextRequest,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> TextResponse:
    result = await ai_service.rewrite_professionally(
        company_id=auth.company_id,
        conversation_id=None,
        text=payload.text,
        actor_user_id=auth.user_id,
    )
    return TextResponse(text=result)


@router.post("/knowledge-search", response_model=KnowledgeSearchResponse)
async def knowledge_search(
    payload: KnowledgeSearchRequest,
    auth: Annotated[AuthContext, Depends(enforce_ai_rate_limit)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
    retrieval: Annotated[KnowledgeRetrievalService, Depends(get_knowledge_retrieval_service)],
    faq_retrieval: Annotated[FaqRetrievalService, Depends(get_faq_retrieval_service)],
) -> KnowledgeSearchResponse:
    """Grounds an answer in hybrid retrieval rather than a substring match.

    Two changes from what this endpoint used to do, both of which change
    the answers it gives:

    **It finds articles the customer did not word the way the author
    did.** The previous implementation passed `search=` to a `ILIKE
    '%query%'` list query, so "can I get my money back" retrieved nothing
    from an article titled "Refund policy" — and the model, correctly and
    uselessly, answered that no relevant articles were found.

    **It grounds on the matching chunk, not the whole article.** A
    4,000-word manual passed in full is mostly tokens about something
    else, and a model given one relevant paragraph inside forty
    irrelevant ones answers worse than one given the paragraph. The
    excerpt is the chunk that actually matched; the body is the fallback
    for a hit found lexically, where there is no matching chunk to point
    at.
    """
    hits = await retrieval.grounding_passages(
        company_id=auth.company_id, query=payload.query, limit=5
    )
    candidates = [(hit.article.title, hit.excerpt or hit.article.body) for hit in hits]
    # "FAQ Search" is now a real retrieval against a real entity rather
    # than another name for this one. Published FAQs are handed over as
    # *approved answers* and articles as reference material — see
    # ``AiService.answer_from_knowledge_base`` for why the distinction is
    # made in the prompt rather than by merging them.
    faq_hits = await faq_retrieval.grounding_answers(
        company_id=auth.company_id, query=payload.query, limit=3
    )
    faq_candidates = [(hit.faq.question, hit.faq.answer) for hit in faq_hits]
    answer = await ai_service.answer_from_knowledge_base(
        company_id=auth.company_id,
        conversation_id=None,
        query=payload.query,
        candidate_articles=candidates,
        candidate_faqs=faq_candidates,
        actor_user_id=auth.user_id,
    )
    return KnowledgeSearchResponse(answer=answer)
