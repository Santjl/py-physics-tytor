from fastapi import FastAPI

from app.api.routes import health, questionnaires, auth, documents


def create_app() -> FastAPI:
    app = FastAPI(title="Physics Tutor API", version="0.1.0")
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(questionnaires.router)
    return app


app = create_app()
