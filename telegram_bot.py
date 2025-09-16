# telegram_bot.py

import telebot
from telebot import types
import json
import logging
import logging.handlers
import asyncio
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.mcp_tools.schemas_llm import (
    NlpRequestParams, DialogTurn,
    BookingOptionResult, CreateReservationResult, CancelReservationResult,
    CancelReservationToolParams,
    HotelAvailabilityToolParams, CreateReservationToolParams,
    GetHotelPublicInfoParams, HotelPublicInfoResult,
    GuestDetailLLM, CustomerDetailLLM
)
from app.mcp_tools.tools import (
    get_exely_booking_options,
    create_exely_reservation_and_get_link,
    cancel_exely_reservation,
    get_hotel_public_info
)
from fastmcp import Client as FastMCPClient
from fastmcp.exceptions import ClientError as FastMCPClientError

try:
    from mcp.types import CallToolResult as MCPCallToolResult, TextContent
    logger_mcp_types_load = logging.getLogger("telegram_bot.mcp_types_loaded_ok")
    logger_mcp_types_load.info("Successfully imported MCPCallToolResult, TextContent from 'mcp.types'.")
except ImportError:
    logger_mcp_types_load = logging.getLogger("telegram_bot.mcp_types_fallback")
    logger_mcp_types_load.warning("Failed to import types from 'mcp.types'. Using dict as fallback. Ensure 'mcp-protocol' is installed.")
    MCPCallToolResult = dict # type: ignore
    TextContent = dict # type: ignore

log_level_str_bot = settings.LOG_LEVEL.upper()
if settings.DEBUG_MODE and log_level_str_bot not in ["DEBUG", "TRACE"]:
    log_level_bot_to_set = logging.DEBUG
else:
    log_level_bot_to_set = getattr(logging, log_level_str_bot, logging.INFO)

logger_root = logging.getLogger()
logger = logging.getLogger("telegram_bot")
logger.setLevel(log_level_bot_to_set)

if not any(isinstance(h, logging.StreamHandler) for h in logger_root.handlers):
    if not logger_root.handlers:
        logging.basicConfig(
            level=log_level_bot_to_set,
            format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

try:
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == settings.TELEGRAM_BOT_LOG_FILE for h in logger.handlers):
        telegram_bot_file_handler = logging.handlers.RotatingFileHandler(
            settings.TELEGRAM_BOT_LOG_FILE, maxBytes=10*1024*1024, backupCount=3, encoding='utf-8'
        )
        telegram_bot_file_handler.setLevel(log_level_bot_to_set)
        file_formatter_bot = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s', '%Y-%m-%d %H:%M:%S')
        telegram_bot_file_handler.setFormatter(file_formatter_bot)
        logger.addHandler(telegram_bot_file_handler)
        logger.propagate = False
        logger.info(f"Логи Telegram бота будут записываться в файл: {settings.TELEGRAM_BOT_LOG_FILE} с уровнем {log_level_str_bot}")
    else:
        logger.info(f"File handler for {settings.TELEGRAM_BOT_LOG_FILE} already exists.")
except Exception as e:
    logger.error(f"Ошибка настройки файлового логгера для Telegram бота: {e}", exc_info=True)


if not settings.TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN не установлен. Бот не может запуститься.")
    exit()

bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN, threaded=False, parse_mode="HTML")

MCP_SERVER_URL_FOR_CLIENT = f"http://{settings.MCP_SERVER_HOST}:{settings.MCP_SERVER_PORT}/mcp_api/mcp"
logger.info(f"Telegram бот будет подключаться к MCP серверу по адресу: {MCP_SERVER_URL_FOR_CLIENT}")
mcp_client = FastMCPClient(MCP_SERVER_URL_FOR_CLIENT)

user_states: Dict[int, Dict[str, Any]] = {}

USER_ACTION_AWAITING_CLARIFICATION = "awaiting_clarification_llm"
USER_ACTION_AWAITING_OPTION_CHOICE = "awaiting_option_choice"
USER_ACTION_AWAITING_BOOKING_DETAILS = "awaiting_booking_details_llm"

def get_or_init_state(user_id: int) -> Dict[str, Any]:
    if user_id not in user_states:
        user_states[user_id] = {"action": None, "data": {}}
    state_data = user_states[user_id].setdefault("data", {})
    state_data.setdefault("llm_dialog_turns", [])
    state_data.setdefault("context_hotel_info", None)
    state_data.setdefault("context_check_in_date", None)
    state_data.setdefault("context_check_out_date", None)
    state_data.setdefault("context_num_adults", None)
    state_data.setdefault("context_children_ages", [])
    state_data.setdefault("selected_option_id", None)
    state_data.setdefault("selected_guarantee_code", None)
    state_data.setdefault("current_search_options_details", {})
    state_data.setdefault("selected_option_details", {})
    state_data.setdefault("context_customer_info", None)
    return user_states[user_id]

def reset_user_action_and_search_context(user_id: int):
    state = get_or_init_state(user_id)
    state["action"] = None
    state_data = state["data"]
    state_data.pop("current_search_options_display", None)
    state_data["current_search_options_details"] = {}
    state_data["selected_option_id"] = None
    state_data["selected_guarantee_code"] = None
    state_data["selected_option_details"] = {}
    logger.debug(f"Пользователь {user_id}: сброшены действие и данные о текущем поиске/выборе.")

def reset_full_search_parameters(user_id: int, reset_hotel_info: bool = False):
    state = get_or_init_state(user_id)
    state_data = state["data"]
    state_data["context_check_in_date"] = None
    state_data["context_check_out_date"] = None
    state_data["context_num_adults"] = None
    state_data["context_children_ages"] = []
    state_data["context_customer_info"] = None
    if reset_hotel_info:
         state_data["context_hotel_info"] = None
         logger.debug(f"Пользователь {user_id}: сброшены параметры поиска, инфо о заказчике и отеле.")
    else:
        logger.debug(f"Пользователь {user_id}: сброшены параметры поиска (даты, гости) и инфо о заказчике. Информация об отеле сохранена.")

def add_to_dialog_history(user_id: int, role: str, content: str):
    state = get_or_init_state(user_id)
    current_turns: List[DialogTurn] = state["data"].setdefault("llm_dialog_turns", [])
    if current_turns and current_turns[-1].role == role and current_turns[-1].content == content:
        logger.debug(f"Пропуск добавления дублирующего сообщения в историю для user_id {user_id}: [{role}] {content[:50]}...")
        return
    current_turns.append(DialogTurn(role=role, content=content))
    if len(current_turns) > settings.LLM_DIALOG_HISTORY_LENGTH:
        state["data"]["llm_dialog_turns"] = current_turns[-settings.LLM_DIALOG_HISTORY_LENGTH:]

async def call_mcp_tool_orchestrator(user_id: int, raw_request: str, current_bot_action: Optional[str]) -> Any:
    state = get_or_init_state(user_id)
    dialog_history = state["data"].get("llm_dialog_turns", [])
    context_hotel_info_for_nlp = state["data"].get("context_hotel_info")
    if isinstance(context_hotel_info_for_nlp, HotelPublicInfoResult):
        context_hotel_info_for_nlp = context_hotel_info_for_nlp.model_dump(exclude_none=True)
    elif hasattr(context_hotel_info_for_nlp, 'model_dump'):
        context_hotel_info_for_nlp = context_hotel_info_for_nlp.model_dump(exclude_none=True)

    context_customer_info_for_nlp = state["data"].get("context_customer_info")
    if isinstance(context_customer_info_for_nlp, CustomerDetailLLM):
        context_customer_info_for_nlp = context_customer_info_for_nlp.model_dump(exclude_none=True)
    elif hasattr(context_customer_info_for_nlp, 'model_dump'):
        context_customer_info_for_nlp = context_customer_info_for_nlp.model_dump(exclude_none=True)

    nlp_params = NlpRequestParams(
        raw_request=raw_request, user_id=str(user_id), dialog_history=dialog_history,
        context_booking_option_id=state["data"].get("selected_option_id"),
        context_guarantee_code=state["data"].get("selected_guarantee_code"),
        context_check_in_date=state["data"].get("context_check_in_date"),
        context_check_out_date=state["data"].get("context_check_out_date"),
        context_num_adults=state["data"].get("context_num_adults"),
        context_children_ages=state["data"].get("context_children_ages"),
        context_hotel_info=context_hotel_info_for_nlp,
        context_customer_info=context_customer_info_for_nlp,
        current_bot_action=current_bot_action
    )
    logger.debug(f"Вызов 'process_natural_language_request' для пользователя {user_id} с параметрами: {nlp_params.model_dump_json(indent=2 if settings.DEBUG_MODE else None, exclude_none=True)}")
    tool_args_dict = {"params": nlp_params.model_dump(mode='json', exclude_none=True)}

    try:
        async with mcp_client:
            mcp_call_result: MCPCallToolResult = await mcp_client.call_tool_mcp("process_natural_language_request", tool_args_dict) # type: ignore
        if settings.DEBUG_MODE:
             logger.debug(f"Ответ от оркестратора MCP CallToolResult: {mcp_call_result.model_dump_json(indent=2) if hasattr(mcp_call_result, 'model_dump_json') else mcp_call_result}") # type: ignore
        if hasattr(mcp_call_result, 'isError') and mcp_call_result.isError: # type: ignore
            error_message = "Неизвестная ошибка от инструмента оркестратора."
            if hasattr(mcp_call_result, 'error') and mcp_call_result.error: # type: ignore
                if isinstance(mcp_call_result.error, str): error_message = mcp_call_result.error # type: ignore
                elif isinstance(mcp_call_result.error, dict) and mcp_call_result.error.get("message"): error_message = mcp_call_result.error["message"] # type: ignore
            logger.error(f"Инструмент оркестратора вернул ошибку в MCPCallResult: {error_message}")
            return {"_mcp_tool_error_": True, "message": error_message}
        if not mcp_call_result.content or not (isinstance(mcp_call_result.content[0], TextContent if TextContent is not dict else dict)): # type: ignore
            logger.error("Инструмент оркестратора не вернул контент или вернул неожиданный тип контента.")
            return {"_mcp_tool_error_": True, "message": "Инструмент оркестратора вернул неожиданный контент."}
        tool_output_str = mcp_call_result.content[0].text if TextContent is not dict else mcp_call_result.content[0].get("text", "") # type: ignore
        logger.debug(f"Вывод инструмента оркестратора (строка): {tool_output_str[:500] + '...' if len(tool_output_str) > 500 else tool_output_str}")
        try:
            if tool_output_str.strip().startswith("```json"): tool_output_str = tool_output_str.strip()[7:-3].strip()
            elif tool_output_str.strip().startswith("```"): tool_output_str = tool_output_str.strip()[3:-3].strip()
            parsed_llm_directive = json.loads(tool_output_str)
            if isinstance(parsed_llm_directive, dict) and "error" in parsed_llm_directive:
                 logger.warning(f"Директива LLM содержит ошибку: {parsed_llm_directive['error']}")
                 return {"_mcp_tool_error_": True, "message": parsed_llm_directive["error"]}
            return parsed_llm_directive
        except json.JSONDecodeError:
            logger.error(f"Не удалось декодировать JSON из результата LLM оркестратора: {tool_output_str}")
            return {"_mcp_tool_error_": True, "message": "Некорректная JSON строка ответа от LLM оркестратора."}
    except FastMCPClientError as e:
        logger.error(f"Ошибка FastMCPClient при вызове оркестратора: {e}", exc_info=True)
        details = str(e)
        user_message = f"Ошибка клиента MCP: {e.message or 'Нет деталей'}"
        if e.response_data:
            details += f" | Response data: {e.response_data}"
            if isinstance(e.response_data, dict):
                status_code = e.response_data.get("status_code")
                error_body_str = e.response_data.get("body")
                if status_code == 429 or (error_body_str and "rate limit" in error_body_str.lower()) or \
                   (error_body_str and "capacity exceeded" in error_body_str.lower()):
                    user_message = "В данный момент сервис перегружен. Пожалуйста, попробуйте позже."

        return {"_mcp_client_error_": True, "message": user_message, "details": details}
    except Exception as e:
        logger.error(f"Неожиданная ошибка при вызове инструмента оркестратора: {e}", exc_info=True)
        return {"_mcp_client_error_": True, "message": f"Вызов оркестратора не удался: {str(e)}", "exception_type": type(e).__name__}

@bot.message_handler(commands=['start', 'help'])
def send_welcome_sync(message: types.Message):
    user_id = message.chat.id
    state = get_or_init_state(user_id)
    state["action"] = "start_command"
    reset_full_search_parameters(user_id, reset_hotel_info=True)
    state["data"]["llm_dialog_turns"] = []
    logger.debug(f"Пользователь {user_id} использовал /start или /help. Состояние, ВЕСЬ КОНТЕКСТ и история диалога полностью сброшены.")

    base_welcome_text = (
        "Добро пожаловать!\n"
        "Команды:\n"
        "/findhotel - Новый поиск отеля (или просто напишите ваш запрос)\n"
        "/cancelbooking - Отменить бронирование (Синтаксис: /cancelbooking НОМЕР_БРОНИ КОД_ОТМЕНЫ)"
    )
    bot.send_message(user_id, base_welcome_text)
    asyncio.run(handle_text_messages_async(message, is_command_start=True))

@bot.message_handler(commands=['findhotel'])
def find_hotel_command_sync(message: types.Message):
    user_id = message.chat.id
    state = get_or_init_state(user_id)
    state["action"] = "findhotel_command"
    reset_user_action_and_search_context(user_id)
    reset_full_search_parameters(user_id, reset_hotel_info=False)
    logger.debug(f"Пользователь {user_id} использовал /findhotel. Контекст поиска и параметры гостей сброшены. Контекст отеля (если был) сохранен.")
    prompt_text = "Какой номер вы ищете? Пожалуйста, опишите ваши потребности (даты, количество гостей, возраст детей и т.д.)."
    bot.send_message(user_id, prompt_text)
    add_to_dialog_history(user_id, "assistant", prompt_text)
    state["action"] = USER_ACTION_AWAITING_CLARIFICATION
    user_states[user_id] = state


@bot.message_handler(commands=['cancelbooking'])
def cancel_booking_start_sync(message: types.Message):
    logger.debug(f"Пользователь {message.chat.id} инициировал /cancelbooking.")
    asyncio.run(cancel_booking_start_async(message))

async def cancel_booking_start_async(message: types.Message):
    user_id = message.chat.id
    state = get_or_init_state(user_id)
    add_to_dialog_history(user_id, "user", message.text)
    args = message.text.split()
    if len(args) == 3:
        booking_number = args[1]; cancellation_code = args[2]
        bot.send_message(user_id, f"Пытаюсь отменить бронирование {booking_number}...")
        tool_params = CancelReservationToolParams(booking_number=booking_number, cancellation_code=cancellation_code, language=settings.DEFAULT_LANGUAGE_LLM)
        actual_tool_result: Union[CancelReservationResult, Dict[str, Any]] = await cancel_exely_reservation(tool_params)
        response_message = ""
        if isinstance(actual_tool_result, CancelReservationResult):
            response_message = f"Результат отмены для {actual_tool_result.booking_number}: {actual_tool_result.message} (Статус: {actual_tool_result.status})"
            if actual_tool_result.status.lower() != "cancelled" and actual_tool_result.error_details and settings.DEBUG_MODE:
                response_message += f"\nДетали: {json.dumps(actual_tool_result.error_details, indent=2, ensure_ascii=False)}"
        elif isinstance(actual_tool_result, dict) and (actual_tool_result.get("_mcp_client_error_") or actual_tool_result.get("_mcp_tool_error_")):
            response_message = f"Отмена не удалась: {actual_tool_result.get('message', 'Неизвестная ошибка при выполнении инструмента отмены.')}"
        else:
            logger.error(f"Неожиданный тип результата от cancel_exely_reservation: {type(actual_tool_result)}, содержимое: {actual_tool_result}")
            response_message = "Попытка отмены привела к неожиданному ответу."
        bot.send_message(user_id, response_message)
        add_to_dialog_history(user_id, "assistant", response_message)
        if "ошибка" not in response_message.lower() and "failed" not in response_message.lower() and \
           isinstance(actual_tool_result, CancelReservationResult) and actual_tool_result.status.lower() == "cancelled":
            reset_user_action_and_search_context(user_id)
            reset_full_search_parameters(user_id, reset_hotel_info=True)
    else:
        reply_text = "Использование: /cancelbooking ВАШ_НОМЕР_БРОНИРОВАНИЯ ВАШ_КОД_ОТМЕНЫ"
        bot.reply_to(message, reply_text)
        add_to_dialog_history(user_id, "assistant", reply_text)
    state["action"] = None
    user_states[user_id] = state

@bot.message_handler(content_types=['text'], func=lambda message: not message.text.startswith('/'))
def handle_plain_text_messages_sync(message: types.Message):
    asyncio.run(handle_text_messages_async(message))

async def handle_text_messages_async(message: types.Message, is_command_start: bool = False):
    user_id = message.chat.id
    text_to_process = message.text.strip() if message.text else ""
    state = get_or_init_state(user_id)
    state_data = state["data"]

    current_bot_action_for_llm = state.get("action")

    text_for_llm_orchestrator = text_to_process
    if is_command_start:
        if text_to_process.lower().strip() in ["/start", "/help"]:
            text_for_llm_orchestrator = "привет" # Use a consistent trigger for initial greeting logic
            current_bot_action_for_llm = "start_command"
    else:
        add_to_dialog_history(user_id, "user", text_to_process)

    bot.send_chat_action(user_id, 'typing')
    logger.debug(f"Пользователь {user_id}, Состояние до LLM: {current_bot_action_for_llm}, Текст для LLM: '{text_for_llm_orchestrator}'")

    llm_directive = await call_mcp_tool_orchestrator(user_id, text_for_llm_orchestrator, current_bot_action_for_llm)

    user_friendly_error_message = "Произошла техническая проблема. Пожалуйста, попробуйте еще раз чуть позже."

    if isinstance(llm_directive, dict) and llm_directive.get("_llm_rate_limit_exceeded_"):
        rate_limit_message = llm_directive.get("clarification_needed",
                                               "Кажется, сейчас я немного перегружен. Пожалуйста, попробуйте через минуту.")
        bot.send_message(user_id, rate_limit_message)
        add_to_dialog_history(user_id, "assistant_system_message", rate_limit_message)
        user_states[user_id] = state
        return

    if isinstance(llm_directive, dict) and (llm_directive.get("_mcp_client_error_") or llm_directive.get("_mcp_tool_error_")):
        error_msg_from_orchestrator = llm_directive.get("message", user_friendly_error_message)
        # Check if it's a specific user-friendly message (like rate limit) or a generic one
        if "сервис перегружен" in error_msg_from_orchestrator.lower() or "попробуйте позже" in error_msg_from_orchestrator.lower():
            bot.send_message(user_id, error_msg_from_orchestrator)
        else:
            bot.send_message(user_id, user_friendly_error_message)

        detailed_error_for_log = llm_directive.get("details") or llm_directive.get("message", "Нет деталей")
        logger.error(f"Ошибка оркестратора для пользователя {user_id}: {detailed_error_for_log}")
        add_to_dialog_history(user_id, "assistant_error", f"Ошибка оркестратора: {detailed_error_for_log}")
        state["action"] = None
        user_states[user_id] = state
        return

    clarification_needed = llm_directive.get("clarification_needed")
    tool_name_to_call = llm_directive.get("tool_name")
    tool_arguments_from_llm = llm_directive.get("arguments", {})

    # Filter out LLM's meta-instructions from clarification_needed
    if clarification_needed and "ответ на вопрос на основе 'description'" in clarification_needed:
        hotel_name_in_ctx = state_data.get("context_hotel_info", {}).get("name", settings.DEFAULT_HOTEL_CODE)
        clarification_needed = f"Привет! Я ваш ассистент по отелю '{hotel_name_in_ctx}'. Чем могу помочь с информацией или бронированием?"
        logger.warning(f"LLM вернул мета-ответ, заменяю на: {clarification_needed}")
        # If this was the only thing LLM wanted to do, treat it as no tool call
        if not tool_name_to_call or tool_name_to_call.lower() == "null":
            bot.send_message(user_id, clarification_needed)
            add_to_dialog_history(user_id, "assistant", clarification_needed)
            state["action"] = USER_ACTION_AWAITING_CLARIFICATION # Or None
            user_states[user_id] = state
            return


    if clarification_needed and str(clarification_needed).strip().lower() != "null" and clarification_needed.strip():
        bot.send_message(user_id, clarification_needed, parse_mode="HTML")
        if tool_name_to_call == "create_exely_reservation_and_get_link":
            state["action"] = USER_ACTION_AWAITING_BOOKING_DETAILS
        elif tool_name_to_call == "get_exely_booking_options":
            state["action"] = USER_ACTION_AWAITING_CLARIFICATION
        elif state.get("action") == USER_ACTION_AWAITING_OPTION_CHOICE:
             state["action"] = USER_ACTION_AWAITING_BOOKING_DETAILS
        else:
            state["action"] = USER_ACTION_AWAITING_CLARIFICATION
        add_to_dialog_history(user_id, "assistant_clarification", clarification_needed)
        user_states[user_id] = state
        return

    if not tool_name_to_call or tool_name_to_call.lower() == "null":
        response_text = clarification_needed or "Я не совсем понял, что вы имеете в виду. Можете перефразировать?"
        # If the only thing LLM returned was the filtered meta-instruction, this block will be hit.
        if "Привет! Я ваш ассистент по отелю" in response_text and state_data.get("context_hotel_info"): # Avoid sending generic if we just loaded hotel info
             pass # Bot already sent hotel info or will send it if it's a new session
        else:
            bot.send_message(user_id, response_text)
        add_to_dialog_history(user_id, "assistant", response_text)
        state["action"] = None
        user_states[user_id] = state
        return

    actual_tool_result: Any = None
    bot.send_chat_action(user_id, 'typing')
    logger.info(f"LLM решил вызвать инструмент: {tool_name_to_call} с аргументами: {tool_arguments_from_llm}")

    try:
        if tool_name_to_call == "get_hotel_public_info":
            try: tool_params = GetHotelPublicInfoParams(**tool_arguments_from_llm)
            except ValidationError as ve:
                logger.error(f"LLM сгенерировал неверные аргументы для {tool_name_to_call}: {ve.errors(include_url=False)}. Аргументы: {tool_arguments_from_llm}")
                error_messages = [f"Поле '{' -> '.join(map(str, err['loc'])) if err['loc'] else 'общее'}': {err['msg']}" for err in ve.errors(include_url=False)]
                clarify_msg = f"Кажется, мне не хватает деталей для запроса информации об отеле. В частности: {'; '.join(error_messages)}. Не могли бы вы уточнить?"
                bot.send_message(user_id, clarify_msg); add_to_dialog_history(user_id, "assistant_clarification", clarify_msg)
                state["action"] = USER_ACTION_AWAITING_CLARIFICATION; user_states[user_id] = state; return

            actual_tool_result = await get_hotel_public_info(tool_params)

            if isinstance(actual_tool_result, HotelPublicInfoResult) and actual_tool_result.name != f"Информация об отеле {tool_params.hotel_code} не найдена":
                state_data["context_hotel_info"] = actual_tool_result.raw_hotel_details_for_context
                hotel_info_msg_parts = []
                display_name = actual_tool_result.name or f"Отель {actual_tool_result.hotel_code}"
                if actual_tool_result.logo_url:
                    try: bot.send_photo(user_id, actual_tool_result.logo_url, caption=f"<b>{display_name}</b>", parse_mode="HTML")
                    except Exception as e_logo:
                        logger.warning(f"Не удалось отправить логотип отеля {display_name}: {e_logo}")
                        hotel_info_msg_parts.append(f"<b>{display_name}</b>" + (f" ({actual_tool_result.stars}*)" if actual_tool_result.stars else ""))
                else:
                     hotel_info_msg_parts.append(f"<b>{display_name}</b>" + (f" ({actual_tool_result.stars}*)" if actual_tool_result.stars else ""))

                desc_clean = actual_tool_result.description.replace('<br>', '\n').replace('<p>', '').replace('</p>','') if actual_tool_result.description else ""
                if desc_clean: hotel_info_msg_parts.append(f"\n{desc_clean[:300]}{'...' if len(desc_clean) > 300 else ''}")
                if actual_tool_result.address: hotel_info_msg_parts.append(f"\nАдрес: {actual_tool_result.address}")
                if actual_tool_result.phone: hotel_info_msg_parts.append(f"Телефон: {actual_tool_result.phone}")
                if actual_tool_result.check_in_time and actual_tool_result.check_out_time:
                    hotel_info_msg_parts.append(f"Заезд: {actual_tool_result.check_in_time}, Выезд: {actual_tool_result.check_out_time}")
                if actual_tool_result.services_summary:
                    hotel_info_msg_parts.append(f"\nОсновные услуги: {', '.join(actual_tool_result.services_summary)}")

                hotel_info_message_to_user = "\n".join(filter(None, hotel_info_msg_parts))
                if hotel_info_message_to_user.strip():
                    bot.send_message(user_id, hotel_info_message_to_user, parse_mode="HTML")

                add_to_dialog_history(user_id, "system_tool_result", f"Получена информация об отеле: {display_name}. Описание: {desc_clean[:50]}...")

                # For /start or "привет", LLM will be called again to generate the actual greeting using the new context
                next_raw_request_for_llm_after_hotel_info = "привет" # Standard greeting trigger
                if not is_command_start and text_for_llm_orchestrator.lower() not in ["/start", "/help", "привет"]:
                     next_raw_request_for_llm_after_hotel_info = text_for_llm_orchestrator # If user asked something else, use that

                logger.debug(f"После get_hotel_public_info, следующий запрос к LLM: '{next_raw_request_for_llm_after_hotel_info}' для user_id {user_id}")

                message_content_dict = {"text": next_raw_request_for_llm_after_hotel_info}
                message_json_string = json.dumps(message_content_dict)

                next_message_obj = types.Message(
                    message_id=message.message_id + 1000,
                    from_user=message.from_user, # type: ignore
                    date=int(datetime.now().timestamp()),
                    chat=message.chat, # type: ignore
                    content_type='text',
                    options={},
                    json_string=message_json_string
                )
                next_message_obj.text = next_raw_request_for_llm_after_hotel_info

                await handle_text_messages_async(next_message_obj, is_command_start=False)
                return
            else:
                error_msg_hotel = actual_tool_result.name if actual_tool_result and actual_tool_result.name else "Не удалось получить информацию об отеле."
                bot.send_message(user_id, error_msg_hotel); add_to_dialog_history(user_id, "assistant_error", error_msg_hotel)
                state["action"] = None; user_states[user_id] = state; return

        elif tool_name_to_call == "get_exely_booking_options":
            try: tool_params = HotelAvailabilityToolParams(**tool_arguments_from_llm)
            except ValidationError as ve:
                logger.error(f"LLM сгенерировал неверные аргументы для {tool_name_to_call}: {ve.errors(include_url=False)}. Аргументы: {tool_arguments_from_llm}")
                error_messages = [f"Поле '{' -> '.join(map(str, err['loc'])) if err['loc'] else 'общее'}': {err['msg']}" for err in ve.errors(include_url=False)]
                clarify_msg = f"Кажется, мне не хватает некоторых деталей для поиска. В частности: {'; '.join(error_messages)}. Не могли бы вы уточнить?"
                bot.send_message(user_id, clarify_msg); add_to_dialog_history(user_id, "assistant_clarification", clarify_msg)
                state["action"] = USER_ACTION_AWAITING_CLARIFICATION; user_states[user_id] = state; return

            state_data["context_check_in_date"] = tool_params.check_in_date
            state_data["context_check_out_date"] = tool_params.check_out_date
            state_data["context_num_adults"] = tool_params.num_adults
            state_data["context_children_ages"] = tool_params.children_ages or []
            logger.debug(f"Контекст поиска сохранен перед вызовом get_exely_booking_options: {tool_params.model_dump_json(exclude_none=True)}")

            reset_user_action_and_search_context(user_id)
            actual_tool_result = await get_exely_booking_options(tool_params)

        elif tool_name_to_call == "create_exely_reservation_and_get_link":
            final_args_for_create = tool_arguments_from_llm.copy()
            if state_data.get("selected_option_id"): final_args_for_create["booking_option_id"] = state_data["selected_option_id"]
            if state_data.get("selected_guarantee_code"): final_args_for_create["guarantee_code"] = state_data["selected_guarantee_code"]

            if not final_args_for_create.get("booking_option_id") or not final_args_for_create.get("guarantee_code"):
                clarify_msg = "Для продолжения бронирования мне нужен ID выбранного варианта и код гарантии. Пожалуйста, выберите вариант из поиска или предоставьте эти данные."
                bot.send_message(user_id, clarify_msg); add_to_dialog_history(user_id, "assistant_clarification", clarify_msg)
                state["action"] = USER_ACTION_AWAITING_OPTION_CHOICE; user_states[user_id] = state; return

            try: tool_params = CreateReservationToolParams(**final_args_for_create)
            except ValidationError as ve_create_params:
                logger.error(f"LLM сгенерировал неверные аргументы для create_exely_reservation_and_get_link: {ve_create_params.errors(include_url=False)}. Аргументы: {final_args_for_create}")
                error_messages = [f"Поле '{' -> '.join(map(str, err['loc'])) if err['loc'] else 'общее'}': {err['msg']}" for err in ve_create_params.errors(include_url=False)]
                clarify_msg = f"Для создания бронирования мне не хватает данных. В частности: {'; '.join(error_messages)}. Не могли бы вы предоставить недостающую или исправить информацию?"
                bot.send_message(user_id, clarify_msg); add_to_dialog_history(user_id, "assistant_clarification", clarify_msg)
                state["action"] = USER_ACTION_AWAITING_BOOKING_DETAILS ; user_states[user_id] = state; return

            if "customer" in type(tool_params).model_fields and tool_params.customer:Add minor fix
                 state_data["context_customer_info"] = tool_params.customer.model_dump(exclude_none=True)
                 logger.debug(f"Информация о заказчике сохранена в контекст: {state_data['context_customer_info']}")
            actual_tool_result = await create_exely_reservation_and_get_link(tool_params)

        elif tool_name_to_call == "cancel_exely_reservation":
            try: tool_params = CancelReservationToolParams(**tool_arguments_from_llm)
            except ValidationError as ve_cancel_params:
                logger.error(f"LLM сгенерировал неверные аргументы для cancel_exely_reservation: {ve_cancel_params.errors(include_url=False)}. Аргументы: {tool_arguments_from_llm}")
                error_messages = [f"Поле '{' -> '.join(map(str, err['loc'])) if err['loc'] else 'общее'}': {err['msg']}" for err in ve_cancel_params.errors(include_url=False)]
                clarify_msg = f"Для отмены бронирования мне не хватает данных. В частности: {'; '.join(error_messages)}. Не могли бы вы уточнить?"
                bot.send_message(user_id, clarify_msg); add_to_dialog_history(user_id, "assistant_clarification", clarify_msg)
                state["action"] = USER_ACTION_AWAITING_CLARIFICATION; user_states[user_id] = state; return
            actual_tool_result = await cancel_exely_reservation(tool_params)
        else:
            bot.send_message(user_id, f"Я понял, что вы хотите '{tool_name_to_call}', но я пока не умею выполнять это действие.")
            add_to_dialog_history(user_id, "assistant_error", f"Неподдерживаемый ботом инструмент: {tool_name_to_call}")
            reset_user_action_and_search_context(user_id)
            reset_full_search_parameters(user_id, reset_hotel_info=True)
            state["action"] = None; user_states[user_id] = state; return

    except ValidationError as ve:
        logger.error(f"Ошибка валидации Pydantic для инструмента '{tool_name_to_call}' с аргументами {tool_arguments_from_llm}: {ve.errors(include_url=False)}")
        error_messages = [f"Поле '{' -> '.join(map(str, err['loc'])) if err['loc'] else 'общие'}': {err['msg']}" for err in ve.errors(include_url=False)]
        clarify_msg = f"Мне нужно больше деталей для '{tool_name_to_call}'. В частности: {'; '.join(error_messages)}. Не могли бы вы предоставить недостающую или исправить информацию?"
        bot.send_message(user_id, clarify_msg); add_to_dialog_history(user_id, "assistant_clarification", clarify_msg)
        state["action"] = USER_ACTION_AWAITING_CLARIFICATION; user_states[user_id] = state; return
    except Exception as e_tool_exec:
        logger.error(f"Ошибка при выполнении инструмента '{tool_name_to_call}', определенного LLM: {e_tool_exec}", exc_info=True)
        bot.send_message(user_id, user_friendly_error_message)
        add_to_dialog_history(user_id, "assistant_error", f"Ошибка выполнения {tool_name_to_call}: {str(e_tool_exec)}")
        reset_user_action_and_search_context(user_id); state["action"] = None; user_states[user_id] = state; return

    # --- Обработка результатов инструментов ---
    if actual_tool_result is not None:
        if isinstance(actual_tool_result, dict) and (actual_tool_result.get("_mcp_client_error_") or actual_tool_result.get("_mcp_tool_error_")):
            error_msg = actual_tool_result.get("message", user_friendly_error_message)
            bot.send_message(user_id, error_msg)
            add_to_dialog_history(user_id, "assistant_error", f"Ошибка инструмента: {error_msg}")
            state["action"] = None
        elif isinstance(actual_tool_result, list) and tool_name_to_call == "get_exely_booking_options":
            special_no_option_ids = ["error", "no_options", "no_suitable_options", "no_options_promo", "no_suitable_options_promo"]
            # Date formatting for display
            check_in_display = datetime.strptime(state_data["context_check_in_date"], "%Y-%m-%d").strftime("%d-%m-%Y") if state_data.get("context_check_in_date") else "не указана"
            check_out_display = datetime.strptime(state_data["context_check_out_date"], "%Y-%m-%d").strftime("%d-%m-%Y") if state_data.get("context_check_out_date") else "не указана"

            if actual_tool_result and hasattr(actual_tool_result[0], 'option_id') and actual_tool_result[0].option_id not in special_no_option_ids:
                response_intro_text = f"Найдены варианты на даты {check_in_display} - {check_out_display}:\n" # Added dates
                bot.send_message(user_id, response_intro_text)
                state_data["current_search_options_details"] = {}
                all_options_summary_for_history = []
                for i, option_res_typed in enumerate(actual_tool_result[:3]):
                    if not isinstance(option_res_typed, BookingOptionResult): logger.warning(f"Пропуск невалидного BookingOptionResult: {option_res_typed}"); continue
                    details = option_res_typed.details
                    state_data["current_search_options_details"][option_res_typed.option_id] = details
                    hotel_name_display = details.get("hotel_name", "")
                    room_type_name_display = details.get("room_type_name", f"Тип номера (код {details.get('room_type_code')})")
                    applied_promo_text = details.get("applied_promo_info", "")
                    applied_promo_text_display = f" ({applied_promo_text})" if applied_promo_text else ""

                    # TODO: Extract included services from details if available and add to option_text
                    # services_included_text = "Включено: Завтрак" # Example
                    # option_text += f"\n{services_included_text}"

                    option_text = (f"\n--- Вариант {i+1} ---{applied_promo_text_display}\nОтель: <b>{hotel_name_display}</b>\nНомер: {room_type_name_display}\nЦена: {details.get('total_price')} {details.get('currency')}\nГости: {details.get('guests_summary', 'не указано')}\nПолитика отмены: <i>{details.get('cancellation_policy', 'не указана')}</i>")
                    all_options_summary_for_history.append(f"Вариант {i+1}: {option_res_typed.summary_text}")
                    room_images = details.get("room_images", [])
                    if room_images:
                        media_to_send = []
                        for img_url in room_images[:5]:
                            try: media_to_send.append(types.InputMediaPhoto(media=img_url))
                            except Exception as e_img: logger.warning(f"Не удалось создать InputMediaPhoto для URL {img_url}: {e_img}")
                        if media_to_send:
                            try:
                                if len(media_to_send) == 1: bot.send_photo(user_id, media_to_send[0].media, caption=f"Вариант {i+1}: {room_type_name_display}" if i == 0 else None, parse_mode="HTML")
                                else:
                                    media_to_send[0].caption = f"Вариант {i+1}: <b>{room_type_name_display}</b>"; media_to_send[0].parse_mode = "HTML"
                                    bot.send_media_group(user_id, media=media_to_send)
                            except Exception as e_send_media: logger.error(f"Ошибка отправки медиа для варианта {i+1}: {e_send_media}", exc_info=True)
                    markup_option = types.InlineKeyboardMarkup(); markup_option.add(types.InlineKeyboardButton(f"Бронировать вариант {i+1} ({details.get('total_price')} {details.get('currency')})", callback_data=f"bookopt_{option_res_typed.option_id}" ))
                    bot.send_message(user_id, option_text, reply_markup=markup_option, parse_mode="HTML")

                if not state_data["current_search_options_details"]:
                     final_response_text_history = "Подходящие варианты для отображения не найдены."
                     bot.send_message(user_id, final_response_text_history)
                else: final_response_text_history = response_intro_text + "\n".join(all_options_summary_for_history)
                add_to_dialog_history(user_id, "assistant", final_response_text_history)
                state["action"] = USER_ACTION_AWAITING_OPTION_CHOICE
            else:
                response_text = "Варианты по вашему запросу не найдены."
                if isinstance(actual_tool_result, list) and actual_tool_result and hasattr(actual_tool_result[0], 'summary_text'): response_text = actual_tool_result[0].summary_text
                elif isinstance(actual_tool_result, dict) and actual_tool_result.get("message"): response_text = actual_tool_result.get("message")
                bot.send_message(user_id, response_text); add_to_dialog_history(user_id, "assistant", response_text)
                state["action"] = None
        elif isinstance(actual_tool_result, CreateReservationResult):
            res: CreateReservationResult = actual_tool_result
            selected_details = state_data.get("selected_option_details", {})
            hotel_name_display = selected_details.get("hotel_name", "Отель")
            room_type_name_display = selected_details.get("room_type_name", "Номер")
            total_price_info = f"{selected_details.get('total_price')} {selected_details.get('currency')}"

            check_in_date_str_api = state_data.get("context_check_in_date", "не указана")
            check_out_date_str_api = state_data.get("context_check_out_date", "не указана")
            try:
                check_in_display = datetime.strptime(check_in_date_str_api, "%Y-%m-%d").strftime("%d-%m-%Y") if check_in_date_str_api != "не указана" else "не указана"
                check_out_display = datetime.strptime(check_out_date_str_api, "%Y-%m-%d").strftime("%d-%m-%Y") if check_out_date_str_api != "не указана" else "не указана"
            except ValueError:
                check_in_display, check_out_display = check_in_date_str_api, check_out_date_str_api # Fallback if parsing fails

            guests_for_reservation_ctx: List[GuestDetailLLM] = []
            create_tool_args_for_message = tool_arguments_from_llm
            if "guests" in create_tool_args_for_message and isinstance(create_tool_args_for_message["guests"], list):
                for g_data_ctx in create_tool_args_for_message["guests"]:
                    try: guests_for_reservation_ctx.append(GuestDetailLLM.model_validate(g_data_ctx))
                    except ValidationError: logger.warning(f"Не удалось валидировать данные гостя из tool_arguments_from_llm для сообщения: {g_data_ctx}")

            guest_names_list = [f"{g.first_name} {g.last_name}" for g in guests_for_reservation_ctx]
            guests_summary_for_message = ", ".join(guest_names_list) if guest_names_list else f"{state_data.get('context_num_adults', '?')} гостя(ей)"

            customer_details_from_args = create_tool_args_for_message.get("customer", {})
            customer_name = f"{customer_details_from_args.get('first_name', '')} {customer_details_from_args.get('last_name', '')}".strip()
            customer_phone = customer_details_from_args.get('phone', 'не указан')
            customer_email = customer_details_from_args.get('email', 'не указан')

            message_parts = [f"<b>Результат бронирования (Статус: {res.status.capitalize()})</b>"]
            if res.booking_number: message_parts.append(f"<b>Номер брони: {res.booking_number}</b>")
            if res.cancellation_code: message_parts.append(f"Код отмены: {res.cancellation_code}")
            message_parts.append(f"\n<b>Отель:</b> {hotel_name_display}")
            message_parts.append(f"<b>Тип номера:</b> {room_type_name_display}")
            message_parts.append(f"<b>Даты:</b> с {check_in_display} по {check_out_display}") # Formatted dates
            message_parts.append(f"<b>Гости:</b> {guests_summary_for_message}")
            message_parts.append(f"<b>Общая стоимость:</b> {total_price_info}")
            message_parts.append(f"\n<b>Данные заказчика:</b>")
            message_parts.append(f"  ФИО: {customer_name}")
            message_parts.append(f"  Email: {customer_email}")
            message_parts.append(f"  Телефон: {customer_phone}")

            if res.error_message: message_parts.append(f"\n<b>Примечание от системы:</b> {res.error_message}")

            final_booking_message = "\n".join(message_parts)

            if settings.DEBUG_MODE and res.details_api_errors:
                 final_booking_message += f"\n\n<b>API Ошибки (отладка):</b>\n<pre>{json.dumps(res.details_api_errors, indent=2, ensure_ascii=False)}</pre>"

            markup_booking = types.InlineKeyboardMarkup()

            bot.send_message(user_id, final_booking_message, reply_markup=markup_booking if markup_booking.keyboard else None, parse_mode="HTML")

            if res.payment_url:
                pay_button = types.InlineKeyboardButton("Оплатить", url=res.payment_url)
                markup_booking.add(pay_button)
            if res.booking_number and res.cancellation_code and res.status.lower() not in ["error", "failed", "error_api", "error_internal", "error_unexpected_response", "cancelled"]:
                callback_data_cancel = f"cancel_{res.booking_number}_{res.cancellation_code}"
                cancel_button = types.InlineKeyboardButton("Отменить это бронирование", callback_data=callback_data_cancel)
                markup_booking.add(cancel_button)

            add_to_dialog_history(user_id, "assistant", final_booking_message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "").replace("<pre>", "").replace("</pre>", ""))

            if res.status.lower() not in ["error", "failed", "error_api", "error_internal", "error_unexpected_response", "cancelled"]:
                reset_user_action_and_search_context(user_id)
                reset_full_search_parameters(user_id, reset_hotel_info=True)
            state["action"] = None
        elif isinstance(actual_tool_result, CancelReservationResult):
            res: CancelReservationResult = actual_tool_result
            bot.send_message(user_id, f"Результат отмены: {res.message} (Статус: {res.status})")
            add_to_dialog_history(user_id, "assistant", f"Результат отмены: {res.message} (Статус: {res.status})")
            if res.status.lower() == "cancelled": # Check specifically for cancelled status
                reset_user_action_and_search_context(user_id)
                reset_full_search_parameters(user_id, reset_hotel_info=True)
            state["action"] = None
        elif isinstance(actual_tool_result, HotelPublicInfoResult):
            logger.warning(f"Обработка HotelPublicInfoResult В КОНЦЕ handle_text_messages_async. Это НЕ ОЖИДАЛОСЬ.")
            state["action"] = USER_ACTION_AWAITING_CLARIFICATION
        elif tool_name_to_call not in ["get_exely_booking_options", "get_hotel_public_info"]:
            logger.error(f"Инструмент '{tool_name_to_call}' вернул неожиданный тип результата: {type(actual_tool_result)}, содержимое: {actual_tool_result}")
            fallback_message = "Я обработал ваш запрос, но результат неясен. Не могли бы вы попробовать перефразировать или начать новый поиск?"
            bot.send_message(user_id, fallback_message)
            add_to_dialog_history(user_id, "assistant_error", fallback_message)
            state["action"] = None

    user_states[user_id] = state


@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query_sync(call: types.CallbackQuery):
    asyncio.run(handle_callback_query_async(call))

async def handle_callback_query_async(call: types.CallbackQuery):
    user_id = call.message.chat.id
    state = get_or_init_state(user_id)
    state_data = state["data"]
    logger.debug(f"Callback query от пользователя {user_id}: {call.data}")
    add_to_dialog_history(user_id, "user_action", f"Нажата кнопка: {call.data}")

    if call.data.startswith("bookopt_"):
        option_id_from_callback = call.data.split("bookopt_")[1]
        bot.answer_callback_query(call.id, f"Выбран вариант ID {option_id_from_callback[:8]}...")

        if "current_search_options_details" not in state_data or \
           option_id_from_callback not in state_data["current_search_options_details"]:
            bot.edit_message_text("Извините, детали этого варианта устарели или не найдены. Пожалуйста, выполните новый поиск.", chat_id=user_id, message_id=call.message.message_id)
            reset_user_action_and_search_context(user_id)
            return

        state_data["selected_option_id"] = option_id_from_callback
        selected_details_dict = state_data["current_search_options_details"][option_id_from_callback]
        state_data["selected_option_details"] = selected_details_dict

        available_guarantees = selected_details_dict.get("available_guarantees", [])
        if not available_guarantees or not isinstance(available_guarantees, list) or not available_guarantees[0].get("code"):
            error_msg = "<b>Ошибка:</b> Для этого варианта не найдены способы оплаты/гарантии. Бронирование невозможно."
            logger.error(f"Ошибка для option_id {option_id_from_callback}: {error_msg}. Детали гарантий: {available_guarantees}")
            bot.send_message(user_id, error_msg, parse_mode="HTML")
            add_to_dialog_history(user_id, "assistant_error", error_msg)
            reset_user_action_and_search_context(user_id)
            return
        state_data["selected_guarantee_code"] = available_guarantees[0]["code"]
        logger.info(f"Для варианта {option_id_from_callback} выбран guarantee_code: {state_data['selected_guarantee_code']}")

        try: bot.edit_message_reply_markup(chat_id=user_id, message_id=call.message.message_id, reply_markup=None)
        except Exception as e: logger.warning(f"Не удалось отредактировать разметку сообщения: {e}")

        user_simulated_request = f"Я выбрал вариант бронирования с ID {option_id_from_callback[:8]}. Хочу его забронировать."
        logger.debug(f"Пользователь {user_id} выбрал вариант. Отправляю LLM запрос '{user_simulated_request}' для запроса данных гостей.")

        message_content_dict_cb = {"text": user_simulated_request}
        message_json_string_cb = json.dumps(message_content_dict_cb)

        fake_message_obj = types.Message(
            message_id=call.message.message_id + 1000,
            from_user=call.from_user, # type: ignore
            date=int(datetime.now().timestamp()),
            chat=call.message.chat, # type: ignore
            content_type='text',
            options={},
            json_string=message_json_string_cb
        )
        fake_message_obj.text = user_simulated_request
        await handle_text_messages_async(fake_message_obj, is_command_start=False)

    elif call.data.startswith("cancel_"):
        parts = call.data.split("_", 2)
        if len(parts) == 3:
            _, booking_number, cancellation_code = parts
            bot.answer_callback_query(call.id, f"Пытаюсь отменить бронирование {booking_number}...")
            try: bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id, text=call.message.text + "\n\n(Отмена инициирована...)", reply_markup=None)
            except Exception as e: logger.warning(f"Не удалось отредактировать сообщение после callback отмены: {e}")

            tool_params = CancelReservationToolParams(booking_number=booking_number, cancellation_code=cancellation_code, language=settings.DEFAULT_LANGUAGE_LLM)
            mcp_result: Union[CancelReservationResult, Dict[str, Any]] = await cancel_exely_reservation(tool_params)
            response_message = ""
            if isinstance(mcp_result, CancelReservationResult): response_message = f"Результат отмены для {mcp_result.booking_number}: {mcp_result.message} (Статус: {mcp_result.status})"
            elif isinstance(mcp_result, dict) and (mcp_result.get("_mcp_client_error_") or mcp_result.get("_mcp_tool_error_")): response_message = f"Отмена не удалась: {mcp_result.get('message', 'Неизвестная ошибка при выполнении инструмента отмены.')}"
            else: response_message = "Попытка отмены привела к неожиданному ответу."

            bot.send_message(user_id, response_message)
            add_to_dialog_history(user_id, "assistant", response_message)
            if mcp_result and isinstance(mcp_result, CancelReservationResult) and mcp_result.status.lower() == "cancelled":
                reset_user_action_and_search_context(user_id)
                reset_full_search_parameters(user_id, reset_hotel_info=True)
        else:
            bot.answer_callback_query(call.id, "Неверный формат данных для отмены.")
            logger.warning(f"Неверный формат callback_data для отмены: {call.data}")
        state["action"] = None
    else:
        bot.answer_callback_query(call.id, "Неизвестный выбор или действие.")
    user_states[user_id] = state

def run_bot():
    logger.info(f"Telegram Бот (LLM Версия) запускается с токеном: {settings.TELEGRAM_BOT_TOKEN[:10]}...")
    try:
        bot.polling(non_stop=True, skip_pending=True)
    except Exception as e:
        logger.critical(f"Критическая ошибка в работе бота (polling): {e}", exc_info=True)

if __name__ == '__main__':
    run_bot()
