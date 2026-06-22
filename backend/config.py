import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


class BaseConfig:
    ENV_NAME = os.getenv("FLASK_ENV", "development")
    DEBUG = ENV_NAME == "development"
    TESTING = False
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-too")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.getenv("ACCESS_TOKEN_EXPIRES_MINUTES", "60"))
    )
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "flux_fleet")
    MONGO_SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000"))
    MONGO_CONNECT_TIMEOUT_MS = int(os.getenv("MONGO_CONNECT_TIMEOUT_MS", "5000"))
    MONGO_SOCKET_TIMEOUT_MS = int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", "5000"))
    MASTER_DATA_SEED_RETRIES = int(os.getenv("MASTER_DATA_SEED_RETRIES", "3"))
    MASTER_DATA_SEED_RETRY_DELAY_SECONDS = float(
        os.getenv("MASTER_DATA_SEED_RETRY_DELAY_SECONDS", "1.5")
    )
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ]
    SEED_DEMO_ON_STARTUP = os.getenv("SEED_DEMO_ON_STARTUP", "false").lower() == "true"


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}


def get_config(config_name: str | None = None):
    selected_name = config_name or os.getenv("FLASK_ENV", "development")
    return CONFIG_MAP.get(selected_name, DevelopmentConfig)
