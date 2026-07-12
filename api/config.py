"""Application settings (NFR-6): a single YAML file, overridable via TRACE_* env vars."""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "config" / "settings.yaml"


class Neo4jSettings(BaseModel):
    uri: str
    user: str
    password: str
    database: str


class ResolveSettings(BaseModel):
    auto_match_threshold: float
    no_match_threshold: float
    addressless_confidence_cap: float
    vector_top_k: int


class EmbeddingSettings(BaseModel):
    adapter: str
    model: str
    dimension: int
    region: str


class LLMSettings(BaseModel):
    adapter: str


class SignalSettings(BaseModel):
    fanout_min_parties: int
    fanout_window_days: int


class StreamSettings(BaseModel):
    directory: Path
    resolution_outcome_file: str
    signal_file: str

    @property
    def resolution_outcome_path(self) -> Path:
        return self.directory / self.resolution_outcome_file

    @property
    def signal_path(self) -> Path:
        return self.directory / self.signal_file


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file=SETTINGS_FILE,
        env_prefix="TRACE_",
        env_nested_delimiter="__",
    )

    neo4j: Neo4jSettings
    resolve: ResolveSettings
    embedding: EmbeddingSettings
    llm: LLMSettings
    signal: SignalSettings
    degree_guard_threshold: int
    role_vocabulary: list[str]
    known_source_systems: list[str]
    streams: StreamSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
