from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from cwa.agent.prompts import PROMPT_VERSION
from cwa.api.errors import error
from cwa.api.schemas import AskRequest
from cwa.config import Settings
from cwa.store.db import Database


def create_app(
    settings: Settings | None = None, runner_factory: Callable[[str], Any] | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Database(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        store.close()

    app = FastAPI(title="Carbon Window Agent", lifespan=lifespan)
    app.state.store = store

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error(400, "bad_input", "Invalid request fields")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error(exc.status_code, "http_error", str(exc.detail))

    @app.post("/ask")
    async def ask(body: AskRequest) -> Any:
        try:
            if runner_factory is None:
                from cwa.runtime import build_runner

                runner = build_runner(settings, store, body.question)
            else:
                runner = runner_factory(body.question)
            async with asyncio.timeout(60):
                result = await runner.run(body.question, history=store.history(body.session_id))
            store.save_run(result, body.session_id, body.question)
            return result.model_dump(mode="json", exclude={"trace", "model", "prompt_version"})
        except (TimeoutError, httpx.TimeoutException):
            return error(504, "timeout", "The request timed out; please try again")
        except httpx.HTTPError:
            return error(502, "upstream_failure", "An upstream service failed")
        except ValueError:
            return error(400, "bad_input", "Unable to run with this input or configuration")
        except Exception:
            return error(502, "upstream_failure", "Unable to complete the request")

    @app.get("/runs/{run_id}")
    async def run_trace(run_id: str) -> Any:
        result = store.get_run(run_id)
        return result if result else error(404, "not_found", "Unknown run")

    @app.get("/plans")
    async def plans() -> list[dict[str, Any]]:
        return store.list_plans()

    def transition(plan_id: str, approve: bool) -> dict[str, Any] | JSONResponse:
        try:
            return store.approve_plan(plan_id) if approve else store.reject_plan(plan_id)
        except KeyError:
            return error(404, "not_found", "Unknown plan")
        except ValueError:
            return error(400, "invalid_transition", "Only pending plans can change status")

    @app.post("/plans/{plan_id}/approve")
    async def approve(plan_id: str) -> Any:
        return transition(plan_id, True)

    @app.post("/plans/{plan_id}/reject")
    async def reject(plan_id: str) -> Any:
        return transition(plan_id, False)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "provider": settings.provider,
            "model": "demo-rules-v1" if settings.provider == "demo" else settings.model,
            "prompt_version": PROMPT_VERSION,
        }

    return app
