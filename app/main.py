import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, questionnaires, auth, documents, feedback
from app.core.logging_config import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Physics Tutor API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:  # noqa: BLE001
            logging.exception("Unhandled error")
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(feedback.router)
    app.include_router(questionnaires.router)
    return app


app = create_app()
