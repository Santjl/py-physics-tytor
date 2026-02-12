from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/quiz_db"
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1"
    ollama_embed_model: str = "nomic-embed-text"
    secret_key: str = "change-me"
    access_token_expire_hours: int = 24

    # Hybrid retrieval settings
    retrieval_semantic_weight: float = 0.6
    retrieval_bm25_weight: float = 0.4
    retrieval_candidate_multiplier: int = 3
    retrieval_rrf_k: int = 60
    retrieval_mmr_lambda: float = 0.7
    retrieval_fts_config: str = "portuguese_unaccent"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
