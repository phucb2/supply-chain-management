from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "", "case_sensitive": False}

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "supplychain"
    postgres_user: str = "supplychain"
    postgres_password: str = "supplychain_secret"

    kafka_bootstrap_servers: str = "localhost:9092"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin_secret"

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "api"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
