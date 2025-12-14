# Physics Tutor API (Python)

FastAPI + SQLAlchemy backend to create questionnaires, collect attempts, and power RAG-based feedback with Ollama. This repository will be built in small PRs; this first PR ships the scaffold, Docker setup, database migrations, and basic questionnaire CRUD.

## Stack
- FastAPI, Pydantic v2
- SQLAlchemy 2.0 + Alembic
- PostgreSQL + pgvector
- Pytest
- Ollama (local) for chat + embeddings (RAG planned with LangChain)

## Environment
- `DATABASE_URL` (e.g. `postgresql+psycopg://postgres:postgres@localhost:5432/quiz_db`)
- `APP_ENV` = `dev|test|prod`
- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_CHAT_MODEL` (default `llama3.1`)
- `OLLAMA_EMBED_MODEL` (default `nomic-embed-text`)

## Local setup (host)
1. Install Python 3.11+.
2. `python -m venv .venv && . .venv/Scripts/activate` (or `source .venv/bin/activate` on Unix).
3. `pip install -r requirements.txt`
4. Set `DATABASE_URL` in a `.env` file or environment.
5. Run migrations: `alembic upgrade head`
6. Start API: `uvicorn app.main:app --reload`

OpenAPI docs live at `/docs`.

Auth (PR2):
- Register student: `POST /auth/register` with `{"email": "...", "password": "..."}`.
- Login: `POST /auth/login` (form data `username`, `password`) → bearer token.
- Admin-only endpoints: create questionnaire and add questions. Create an admin row manually or via seed in dev.
- Student-only: submit attempts; student_id is taken from the JWT.

Documents (PR3):
- Upload PDF: `POST /documents/upload` (multipart `file`) as admin. In test env, processing is synchronous; otherwise it runs in a background task.
- Check status: `GET /documents/{id}`.
- PDFs are parsed with PyMuPDF, chunked (~900 chars, 150 overlap), embedded via Ollama embeddings (`OLLAMA_EMBED_MODEL`, default `nomic-embed-text`), and stored in `chunks` with pgvector.
- RAG orchestration will use LangChain in PR4.

## Docker
`docker-compose up --build`

Notes:
- The API reads `DATABASE_URL` from the service environment.
- Ollama is expected on the host at `http://localhost:11434`. The compose file adds `host.docker.internal`; on Linux this requires Docker Engine 20.10+ (host-gateway support).
- If you run the API on host instead of container, ensure it can reach your Postgres instance and Ollama.

## Database migrations
- Create: `alembic revision -m "message"`
- Apply: `alembic upgrade head`
- Downgrade: `alembic downgrade -1`

## Tests
`pytest`

Tests run against an in-memory SQLite database for speed; production uses Postgres/pgvector.

## Seed sample data
`python scripts/seed_sample.py`

Seeds a “Kinematics Basics” questionnaire with one question and options.

## Roadmap (planned PRs)
1. ✅ PR1: Scaffold, Docker, migrations, basic CRUD.
2. PR2: Auth (JWT) + student ownership of attempts.
3. PR3: Document upload, PDF parsing, chunking, embeddings, pgvector storage.
4. PR4: Retrieval + AI feedback with strict citations (LangChain).
5. PR5: Hardening (validation, error handling, logging, evaluation tests).
