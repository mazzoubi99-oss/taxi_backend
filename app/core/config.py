"""
إعدادات التطبيق — تُقرأ من .env
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ===== Database =====
    DB_NAME: str = os.getenv("DB_NAME", "taxi_app")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "123")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")

    # ===== JWT =====
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    REFRESH_SECRET_KEY: str = os.getenv("REFRESH_SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

    # ===== App =====
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "7070"))
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    CORS_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")
    ]

    @property
    def db_dsn(self) -> str:
        return (
            f"dbname={self.DB_NAME} user={self.DB_USER} "
            f"password={self.DB_PASSWORD} host={self.DB_HOST} port={self.DB_PORT}"
        )


settings = Settings()