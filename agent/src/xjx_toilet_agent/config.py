"""Environment settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime config from env / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    toilet_host: str = "192.168.1.34"
    toilet_token: str = ""
    toilet_model: str = "xjx.toilet.relax"
    toilet_mac: str = ""
    toilet_name: str = "小鲸洗马桶"
    miio_timeout: float = 8.0

    seating_interval_sec: float = 5.0
    full_interval_sec: float = 30.0
    poll_gap_sec: float = 0.35

    mqtt_host: str = "192.168.1.249"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    mqtt_prefix: str = "xjx/toilet"
    mqtt_client_id: str = "xjx-toilet-agent"
    mqtt_discovery_prefix: str = "homeassistant"

    log_level: str = "INFO"
