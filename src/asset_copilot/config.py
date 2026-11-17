from datetime import date

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    # Fixed "today" for the synthetic data and the agent, so gold answers are reproducible.
    as_of_date: date = date(2026, 6, 30)
    # Agent loop limits
    max_iterations: int = 8
    max_sql_errors: int = 5
    max_tokens: int = 8192
    max_result_rows_to_model: int = 50
    anthropic_timeout: float = 60.0
    # Documents / retrieval. The schema column is vector(1024): keep the model's dimension in sync.
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_dim: int = 1024
    # bge models retrieve best when queries (not documents) carry this instruction prefix.
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "
    generated_dir: str = "data/generated"
    database_url_admin: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/asset_copilot"
    )
    database_url_readonly: str = (
        "postgresql+psycopg://agent_ro:agent_ro@localhost:5432/asset_copilot"
    )


settings = Settings()
