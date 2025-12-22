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
- Each chunk is classified as `theory`, `exercise`, or `unknown` during ingestion (simple keyword heuristics) and optional chapter/section titles are stored when detected.

Feedback (PR4):
- Generate feedback: `POST /attempts/{attempt_id}/feedback` as the owning student.
- Retrieves similar chunks (pgvector) from theory-only content and prompts Ollama (`OLLAMA_CHAT_MODEL`, default `llama3.1`). If no theory chunks are available, it can fall back to `unknown` but never to exercises.
- Test mode (`APP_ENV=test`) avoids LLM calls and returns deterministic feedback using stored chunks.

Hardening (PR5):
- Basic validation: questionnaire title required; questions require at least one correct option and unique letters.
- Global error guard returns 500 with logged exception; logging configured to stdout.
- CORS open for ease of local use (tighten for prod).
- Evaluation tests: scoring correctness, validation edge cases, feedback output with citations in test mode.

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
