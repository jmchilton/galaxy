from fastapi import (
    FastAPI,
    Request,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

try:
    from starlette_context.middleware import RawContextMiddleware
    from starlette_context.plugins import RequestIdPlugin
except ImportError:
    pass

from galaxy.exceptions import MessageException
from galaxy.web.framework.base import walk_controller_modules
from galaxy.web.framework.decorators import (
    api_error_message,
    validation_error_to_message_exception,
)


def get_error_response_for_request(request: Request, exc: MessageException) -> JSONResponse:
    error_dict = api_error_message(None, exception=exc)
    status_code = exc.status_code
    path = request.url.path
    if "ga4gh" in path:
        # When serving GA4GH APIs use limited exceptions to conform their expected
        # error schema. Tailored to DRS currently.
        content = {"status_code": status_code, "msg": error_dict["err_msg"]}
    else:
        content = error_dict
    return JSONResponse(status_code=status_code, content=content)


def add_exception_handler(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validate_exception_middleware(request: Request, exc: RequestValidationError) -> Response:
        exc = validation_error_to_message_exception(exc)
        return get_error_response_for_request(request, exc)

    @app.exception_handler(MessageException)
    async def message_exception_middleware(request: Request, exc: MessageException) -> Response:
        return get_error_response_for_request(request, exc)


def add_request_id_middleware(app: FastAPI):
    app.add_middleware(RawContextMiddleware, plugins=(RequestIdPlugin(force_new_uuid=True),))


def include_all_package_routers(app: FastAPI, package_name: str):
    for _, module in walk_controller_modules(package_name):
        router = getattr(module, "router", None)
        if router:
            app.include_router(router)
