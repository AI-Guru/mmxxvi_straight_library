from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    page_max_chars: int = 4000
    default_list_limit: int = 20

    # pgvector / Ollama
    postgres_url: str = "postgresql://libraryuser:librarypassword@postgres:5432/librarydb"
    ollama_embed_model: str = "qwen3-embedding:0.6b"
    embedding_dimension: int = 1024
    chunk_size: int = 1000
    chunk_overlap: int = 100

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
