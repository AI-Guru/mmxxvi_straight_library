from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "/app/data/library.db"
    page_max_chars: int = 4000
    default_list_limit: int = 20

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
