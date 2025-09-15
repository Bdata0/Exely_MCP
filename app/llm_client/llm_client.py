# app/llm_client/llm_client.py
import logging
from mistralai import Mistral # Используем актуальный класс клиента
from mistralai.models import SystemMessage, UserMessage # Импортируем нужные типы сообщений
# ChatMessage как отдельный публичный класс для создания сообщений не используется в mistralai >= 1.0.0

from app.config import settings
import json

logger = logging.getLogger(__name__)

if not settings.MISTRAL_API_KEY or settings.MISTRAL_API_KEY == "ВАШ_КЛЮЧ_MISTRAL_API":
    logger.critical("MISTRAL_API_KEY is not set or is a placeholder in .env. LLM calls will fail.")
    # exit("MISTRAL_API_KEY is not configured.") # Раскомментировать, если это критично

mistral_client = Mistral(api_key=settings.MISTRAL_API_KEY)

async def get_llm_response(system_prompt: str, user_prompt: str, model_name: str | None = None) -> dict | None:
    """
    Sends a request to the Mistral API and returns the structured JSON response.
    """
    if not settings.MISTRAL_API_KEY or settings.MISTRAL_API_KEY == "ВАШ_КЛЮЧ_MISTRAL_API":
        logger.error("MISTRAL_API_KEY is not configured. Cannot make LLM call.")
        return {"error": "LLM API key not configured."}

    current_model = model_name or settings.LLM_MODEL_NAME
    logger.debug(f"Sending request to Mistral API. Model: {current_model}")

    if settings.DEBUG_MODE:
        logger.debug(f"System Prompt for LLM: \n{system_prompt}")
        logger.debug(f"User Prompt for LLM: \n{user_prompt}")

    # Используем рекомендованные классы или словари для сообщений
    # Для mistralai >= 1.0.0
    messages_to_send = [
        SystemMessage(content=system_prompt),
        UserMessage(content=user_prompt)
    ]
    # Альтернативно, можно использовать словари:
    # messages_to_send = [
    #     {"role": "system", "content": system_prompt},
    #     {"role": "user", "content": user_prompt}
    # ]

    try:
        # Pydantic v2 может жаловаться на Union (List[Union[SystemMessage, UserMessage...]]),
        # но API Mistral должен принять это. Если нет, передавайте как List[Dict[str, str]].
        chat_response = await mistral_client.chat.complete_async(
            model=current_model,
            messages=messages_to_send, # type: ignore
            response_format={"type": "json_object"}
        )
        response_content = chat_response.choices[0].message.content
        logger.debug(f"Raw LLM response content: {response_content}")

        if response_content:
            try:
                # Иногда LLM может обернуть JSON в markdown code block
                if response_content.strip().startswith("```json"):
                    response_content = response_content.strip()[7:-3].strip()
                elif response_content.strip().startswith("```"): # Общий случай для ```
                    response_content = response_content.strip()[3:-3].strip()

                parsed_response = json.loads(response_content)
                logger.info("Successfully parsed LLM JSON response.")
                return parsed_response
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from LLM response: {e}. Response: {response_content}")
                return {"error": "LLM returned invalid JSON.", "raw_response": response_content}
        logger.warning("LLM response content was empty.")
        return {"error": "LLM response content was empty."}
    except Exception as e:
        logger.error(f"Error calling Mistral API: {e}", exc_info=True)
        api_error_details = ""
        # Попытка извлечь детали из ошибки API, если возможно
        # У Mistral SDK ошибки обычно содержат response атрибут
        if hasattr(e, 'response') and e.response is not None and hasattr(e.response, 'text'):
            try:
                error_data = json.loads(e.response.text)
                api_error_details = error_data.get("message", e.response.text)
            except json.JSONDecodeError:
                api_error_details = e.response.text[:500] # Первые 500 символов
        elif hasattr(e, 'message'): # Некоторые ошибки могут иметь просто message
             api_error_details = str(getattr(e, 'message', str(e))) # getattr для безопасности
        else:
             api_error_details = str(e)

        return {"error": f"LLM API call failed: {str(e)}", "details": api_error_details}
