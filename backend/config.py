import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


PLACEHOLDER_SECRET_VALUES = {
    "change-me",
    "change-me-too",
    "your-secret-key",
    "your-jwt-secret",
    "replace-with-a-secure-random-secret",
    "replace-with-a-secure-random-jwt-secret",
}
DEVELOPMENT_DEFAULT_CORS_ORIGIN = "http://localhost:5173"
DEVELOPMENT_DEFAULT_MONGO_URI = "mongodb://localhost:27017"
LOCALHOST_TOKENS = ("localhost", "127.0.0.1")


class BaseConfig:
    ENV_NAME = os.getenv("FLASK_ENV", "development")
    DEBUG = ENV_NAME == "development"
    TESTING = False
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-too")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.getenv("ACCESS_TOKEN_EXPIRES_MINUTES", "60"))
    )
    MONGO_URI = os.getenv("MONGO_URI", DEVELOPMENT_DEFAULT_MONGO_URI)
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "flux_fleet")
    MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "5"))
    MONGO_SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000"))
    MONGO_CONNECT_TIMEOUT_MS = int(os.getenv("MONGO_CONNECT_TIMEOUT_MS", "5000"))
    MONGO_SOCKET_TIMEOUT_MS = int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", "5000"))
    MASTER_DATA_SEED_RETRIES = int(os.getenv("MASTER_DATA_SEED_RETRIES", "3"))
    MASTER_DATA_SEED_RETRY_DELAY_SECONDS = float(
        os.getenv("MASTER_DATA_SEED_RETRY_DELAY_SECONDS", "1.5")
    )
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", DEVELOPMENT_DEFAULT_CORS_ORIGIN).split(",")
        if origin.strip()
    ]
    SEED_DEMO_ON_STARTUP = os.getenv("SEED_DEMO_ON_STARTUP", "false").lower() == "true"

    @classmethod
    def validate(cls) -> None:
        if cls.ENV_NAME != "production":
            return

        if cls.DEBUG:
            raise RuntimeError("Production configuration is invalid. DEBUG must be False.")

        missing_fields: list[str] = []
        insecure_fields: list[str] = []

        required_values = {
            "SECRET_KEY": cls.SECRET_KEY,
            "JWT_SECRET_KEY": cls.JWT_SECRET_KEY,
            "MONGO_URI": cls.MONGO_URI,
        }
        for field_name, field_value in required_values.items():
            normalized_value = str(field_value or "").strip()
            if not normalized_value:
                missing_fields.append(field_name)
                continue
            if field_name in {"SECRET_KEY", "JWT_SECRET_KEY"} and normalized_value in PLACEHOLDER_SECRET_VALUES:
                insecure_fields.append(field_name)

        cors_env_value = os.getenv("CORS_ORIGINS", "").strip()
        if not cors_env_value:
            missing_fields.append("CORS_ORIGINS")
        elif any(
            localhost_token in origin.lower()
            for origin in cls.CORS_ORIGINS
            for localhost_token in LOCALHOST_TOKENS
        ):
            insecure_fields.append("CORS_ORIGINS")

        mongo_uri = str(cls.MONGO_URI or "").strip().lower()
        if (
            mongo_uri == DEVELOPMENT_DEFAULT_MONGO_URI
            or any(localhost_token in mongo_uri for localhost_token in LOCALHOST_TOKENS)
        ):
            insecure_fields.append("MONGO_URI")

        if missing_fields or insecure_fields:
            problem_parts: list[str] = []
            if missing_fields:
                problem_parts.append(f"missing required values for: {', '.join(sorted(set(missing_fields)))}")
            if insecure_fields:
                problem_parts.append(f"replace insecure production values for: {', '.join(sorted(set(insecure_fields)))}")
            raise RuntimeError(f"Production configuration is invalid. {'; '.join(problem_parts)}.")


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
    config_class = CONFIG_MAP.get(selected_name, DevelopmentConfig)
    config_class.validate()
    return config_class
