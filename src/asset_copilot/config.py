from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    database_url_admin: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/asset_copilot"
    )
    database_url_readonly: str = (
        "postgresql+psycopg://agent_ro:agent_ro@localhost:5432/asset_copilot"
    )


settings = Settings()
