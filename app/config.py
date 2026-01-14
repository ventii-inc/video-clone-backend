from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    db_name: str = "video_clone_db"
    db_user: str = "postgres"
    db_password: str = ""
    db_host: str = "localhost"
    db_port: str = "5432"

    # Environment
    env: str = "development"
    debug: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
