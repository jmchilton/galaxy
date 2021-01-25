"""
This module *does not* contain API routes. It exclusively contains dependencies to be used in FastAPI routes
"""
from typing import (
    cast,
    Optional,
    Type,
    TypeVar,
)

from fastapi import (
    Cookie,
    Header,
    Query,
)
from fastapi.params import Depends
from starlette.requests import Request

from galaxy import (
    app as galaxy_app,
    model,
)
from galaxy.exceptions import AdminRequiredException
from galaxy.managers.session import GalaxySessionManager
from galaxy.managers.users import UserManager
from galaxy.model import User
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.structured_app import StructuredApp
from galaxy.web.framework.decorators import require_admin_message
from galaxy.webapps.base.controller import BaseAPIController
from galaxy.work.context import SessionRequestContext


def get_app() -> StructuredApp:
    return cast(StructuredApp, galaxy_app.app)


T = TypeVar("T")


class GalaxyTypeDepends(Depends):
    """Variant of fastapi Depends that can also work on WSGI Galaxy controllers."""

    def __init__(self, callable, dep_type):
        super().__init__(callable)
        self.galaxy_type_depends = dep_type


def depends(dep_type: Type[T]) -> T:

    def _do_resolve(request: Request):
        return get_app().resolve(dep_type)

    return GalaxyTypeDepends(_do_resolve, dep_type)


def get_session(session_manager: GalaxySessionManager = depends(GalaxySessionManager),
                security: IdEncodingHelper = depends(IdEncodingHelper),
                galaxysession: Optional[str] = Cookie(None)) -> Optional[model.GalaxySession]:
    if galaxysession:
        session_key = security.decode_guid(galaxysession)
        if session_key:
            return session_manager.get_session_from_session_key(session_key)
        # TODO: What should we do if there is no session? Since this is the API, maybe nothing is the right choice?
    return None


def get_api_user(user_manager: UserManager = depends(UserManager), key: Optional[str] = Query(None), x_api_key: Optional[str] = Header(None)) -> Optional[User]:
    api_key = key or x_api_key
    if not api_key:
        return None
    return user_manager.by_api_key(api_key=api_key)


def get_user(galaxy_session: Optional[model.GalaxySession] = Depends(get_session), api_user: Optional[User] = Depends(get_api_user)) -> Optional[User]:
    if galaxy_session:
        return galaxy_session.user
    return api_user


DependsOnUser = Depends(get_user)


def get_trans(app: StructuredApp = depends(StructuredApp), user: Optional[User] = Depends(get_user),
              galaxy_session: Optional[model.GalaxySession] = Depends(get_session),
              ) -> SessionRequestContext:
    app.model.session.expunge_all()
    return SessionRequestContext(app=app, user=user, galaxy_session=galaxy_session)


DependsOnTrans = Depends(get_trans)


def get_admin_user(trans: SessionRequestContext = DependsOnTrans):
    if not trans.user_is_admin:
        raise AdminRequiredException(require_admin_message(trans.app.config, trans.user))
    return trans.user


AdminUserRequired = Depends(get_admin_user)


class BaseGalaxyAPIController(BaseAPIController):

    def __init__(self, app: StructuredApp):
        super().__init__(app)
