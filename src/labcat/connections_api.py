"""Write-only connection routes; the app supplies Host, Origin and CSRF
checks."""

import json

from fastapi import APIRouter, HTTPException, Request

from labcat.chatgpt_auth import ChatGPTSetupError
from labcat.connections import ConnectionManager
from labcat.credentials import (
    ConnectionBusy,
    ConnectionError,
    unique_json_object,
)


async def _body(request: Request) -> dict:
    # Do not use Pydantic error responses here: they may echo secret input.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 24_000:
            raise HTTPException(413, "Connection request is too large.")
    try:
        value = json.loads(raw, object_pairs_hook=unique_json_object)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(
            422, "Connection request must be a supported JSON object."
        ) from None


def _call(function, *args):
    try:
        return function(*args)
    except ChatGPTSetupError as error:
        raise HTTPException(503, {"code": error.code}) from None
    except ConnectionBusy:
        raise HTTPException(
            409,
            "A model connection operation is already in progress. Try again shortly.",
        ) from None
    except ConnectionError as error:
        raise HTTPException(422, str(error)) from None


def create_connections_router(manager: ConnectionManager) -> APIRouter:
    router = APIRouter(prefix="/api/connections")

    @router.get("")
    def status():
        return manager.status()

    @router.get("/setup")
    def setup_status():
        return _call(manager.setup.status)

    @router.put("/setup")
    async def setup_progress(request: Request):
        return _call(manager.setup.save_progress, await _body(request))

    @router.post("/setup/{action}")
    async def setup_action(action: str, request: Request):
        from starlette.concurrency import run_in_threadpool

        if action not in {"verify", "complete"} or await _body(request) != {}:
            raise HTTPException(422, "Choose a supported setup action.")
        operation = (
            manager.setup.verify if action == "verify" else manager.setup.complete
        )
        return await run_in_threadpool(_call, operation)

    @router.put("")
    async def configure(request: Request):
        return _call(manager.configure, await _body(request))

    @router.put("/sources/{source}")
    async def configure_source(source: str, request: Request):
        return _call(manager.configure_source, source, await _body(request))

    @router.post("/accounts")
    async def add_account(request: Request):
        return _call(manager.save_account, await _body(request))

    @router.put("/accounts/{identifier}")
    async def update_account(identifier: str, request: Request):
        return _call(manager.save_account, await _body(request), identifier)

    @router.post("/accounts/{identifier}/select")
    async def select_account(identifier: str, request: Request):
        if await _body(request) != {}:
            raise HTTPException(422, "Select only the named connection.")
        return _call(manager.select_account, identifier)

    @router.post("/models")
    async def models(request: Request):
        from starlette.concurrency import run_in_threadpool

        if await _body(request) != {}:
            raise HTTPException(422, "Model listing uses the saved connection.")
        return await run_in_threadpool(_call, manager.list_models)

    @router.get("/aws-profiles")
    def aws_profiles():
        from labcat.aws import profile_options

        return profile_options()

    @router.get("/agent")
    def agent():
        return _call(manager.agent.runtime_status)

    @router.post("/usage")
    async def usage(request: Request):
        from starlette.concurrency import run_in_threadpool

        if await _body(request) != {}:
            raise HTTPException(422, "Usage lookup uses the saved connection.")
        return await run_in_threadpool(_call, manager.agent.usage)

    @router.post("/accounts/{identifier}/login")
    async def login(identifier: str, request: Request):
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(
            _call, manager.agent.start_login, identifier, await _body(request)
        )

    @router.post("/accounts/{identifier}/login/{flow_id}/{action}")
    async def login_action(
        identifier: str, flow_id: str, action: str, request: Request
    ):
        from starlette.concurrency import run_in_threadpool

        if await _body(request) != {}:
            raise HTTPException(422, "Sign-in actions do not accept credentials.")
        return await run_in_threadpool(
            _call, manager.agent.login_action, identifier, flow_id, action
        )

    @router.post("/accounts/{identifier}/logout")
    async def logout(identifier: str, request: Request):
        if await _body(request) != {}:
            raise HTTPException(422, "Choose only the account to disconnect.")
        return _call(manager.agent.forget_login, identifier)

    @router.post("/local-defaults")
    async def local_defaults(request: Request):
        body = await _body(request)
        if set(body) != {"persist"}:
            raise HTTPException(422, "Supply only the persistence choice.")
        return _call(manager.local_defaults, body["persist"])

    @router.post("/test")
    async def test(request: Request):
        body = await _body(request)
        if set(body) != {"target"} or not isinstance(body["target"], str):
            raise HTTPException(422, "Choose a supported connection test target.")
        # Synchronous network operations run in the normal thread pool.
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(_call, manager.test, body["target"])

    @router.post("/vault")
    async def vault(request: Request):
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(
            _call, manager.vault_action, await _body(request)
        )

    return router
