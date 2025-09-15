# app/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # --- Exely API Configuration ---
    EXELY_API_KEY: str = "YOUR_EXELY_API_KEY_PLACEHOLDER"
    EXELY_BASE_URL: str = "https://ibe.hopenapi.com"
    DEFAULT_HOTEL_CODE: str = "508308"   #"509504"
    EXELY_CLIENT_TIMEOUT: float = 30.0

    # --- Booking Flow Defaults ---
    DEFAULT_LANGUAGE: str = "en-gb" # Для API Exely
    DEFAULT_CURRENCY: str = "GEL" # Для API Exely
    DEFAULT_LANGUAGE_LLM: str = "ru" # Язык для промптов и ответов LLM
    DEFAULT_CURRENCY_LLM: str = "GEL" # Валюта, которую LLM должен ожидать/использовать

    DEFAULT_SUCCESS_URL: str = "https://example.com/booking/success"
    DEFAULT_DECLINE_URL: str = "https://example.com/booking/decline"
    DEFAULT_POS_URL: str = "https://mybookingplatform.com"
    DEFAULT_POS_INTEGRATION_KEY: str = "MY-MCP-AGENT-001"
    DEFAULT_SUBSCRIBE_EMAIL: bool = True

    # --- LLM Configuration ---
    MISTRAL_API_KEY: Optional[str] = None
    LLM_MODEL_NAME: str = "mistral-small-latest"
    LLM_DIALOG_HISTORY_LENGTH: int = 30

    # --- Telegram Bot Configuration ---
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # --- MCP Server Configuration ---
    MCP_SERVER_HOST: str = "127.0.0.1"
    MCP_SERVER_PORT: int = 8000
    MCP_SERVER_NAME: str = "ExelyBookingMCP"
    MCP_SERVER_INSTRUCTIONS: str = "MCP server for booking hotels via Exely API using LLM orchestration."

    # --- Application Settings ---
    APP_NAME: str = "Exely Hotel Booking Assistant"
    DEBUG_MODE: bool = False

    # --- Logging Configuration ---
    LOG_LEVEL: str = "INFO"  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
    MCP_LOG_FILE: str = "mcp_log.txt"
    TELEGRAM_BOT_LOG_FILE: str = "telegram_bot_log.txt"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra='ignore'
    )

settings = Settings()
print(f"ОТЛАДКА config.py: Загружен DEFAULT_HOTEL_CODE: '{settings.DEFAULT_HOTEL_CODE}'")
print(f"ОТЛАДКА config.py: MCP Log File: '{settings.MCP_LOG_FILE}', Telegram Log File: '{settings.TELEGRAM_BOT_LOG_FILE}', Log Level: '{settings.LOG_LEVEL}'")
print(f"ОТЛАДКА config.py: LLM_MODEL_NAME: '{settings.LLM_MODEL_NAME}'")
print(f"ОТЛАДКА config.py: LLM_DIALOG_HISTORY_LENGTH: {settings.LLM_DIALOG_HISTORY_LENGTH}") # Добавлено для отладки
