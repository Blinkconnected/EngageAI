"""FastAPI dependency providers.

These bridge the DI container to route handlers via ``Depends`` and are the
only place API code touches the container directly.
"""

from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.auth_service import AuthService
from blinkengage.application.services.customer_service import CustomerService
from blinkengage.application.services.department_service import DepartmentService
from blinkengage.application.services.team_service import TeamService
from blinkengage.core.auth_context import AuthContext
from blinkengage.core.config import Settings
from blinkengage.core.container import Container
from blinkengage.core.security import InvalidTokenError, TokenType, decode_token
from blinkengage.domain.rbac import is_known_permission
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.tag_repository import TagRepository
from blinkengage.infrastructure.repositories.team_repository import TeamRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository

_bearer_scheme = HTTPBearer(auto_error=True)


def get_settings_dep(request: Request) -> Settings:
    container = cast(Container, request.app.state.container)
    return container.settings()


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession]:
    container = cast(Container, request.app.state.container)
    session_factory = container.session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_redis(request: Request) -> Redis:
    container = cast(Container, request.app.state.container)
    return container.redis()


def get_refresh_token_store(
    redis: Annotated[Redis, Depends(get_redis)],
) -> RefreshTokenStore:
    return RefreshTokenStore(redis)


def get_auth_service(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    refresh_tokens: Annotated[RefreshTokenStore, Depends(get_refresh_token_store)],
) -> AuthService:
    return AuthService(
        settings=settings,
        session=session,
        companies=CompanyRepository(session),
        users=UserRepository(session),
        roles=RoleRepository(session),
        refresh_tokens=refresh_tokens,
    )


def get_current_auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AuthContext:
    try:
        payload = decode_token(
            credentials.credentials, settings=settings, expected_type=TokenType.ACCESS
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return AuthContext(
        user_id=UUID(payload["sub"]),
        company_id=UUID(payload["company_id"]),
        permissions=frozenset(payload.get("permissions", [])),
    )


async def get_current_user(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    user = await UserRepository(session).get_by_id(auth.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is no longer active"
        )
    return user


def get_department_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DepartmentService:
    return DepartmentService(departments=DepartmentRepository(session))


def get_team_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TeamService:
    return TeamService(teams=TeamRepository(session), agents=AgentRepository(session))


def get_agent_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentService:
    return AgentService(
        session=session,
        agents=AgentRepository(session),
        users=UserRepository(session),
        roles=RoleRepository(session),
    )


def get_customer_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomerService:
    return CustomerService(customers=CustomerRepository(session), tags=TagRepository(session))


def require_permission(
    code: str,
) -> Callable[[AuthContext], Coroutine[Any, Any, AuthContext]]:
    """Dependency factory: ``Depends(require_permission("customers.manage"))``.

    Fails fast at import time (not per-request) if ``code`` isn't a known
    permission — catches typos in route definitions during app startup.
    """
    if not is_known_permission(code):
        raise ValueError(f"Unknown permission code: {code!r}")

    async def _check(auth: Annotated[AuthContext, Depends(get_current_auth)]) -> AuthContext:
        if not auth.has_permission(code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {code}",
            )
        return auth

    return _check
