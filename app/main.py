# app/main.py

import logging
import logging.handlers
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.tools import Tool # Import the Tool class

from app.config import settings
from app.mcp_tools import tools as exely_tools


# --- Настройка логирования (без изменений) ---
log_level_str = settings.LOG_LEVEL.upper()
if settings.DEBUG_MODE and log_level_str not in ["DEBUG", "TRACE"]:
    log_level_to_set = logging.DEBUG
    print(f"DEBUG_MODE is True. Overriding LOG_LEVEL from '{settings.LOG_LEVEL}' to 'DEBUG'.")
else:
    log_level_to_set = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(
    level=log_level_to_set,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger_app = logging.getLogger("app")
logger_app.setLevel(log_level_to_set)
logger_fastmcp = logging.getLogger("FastMCP")
logger_fastmcp.setLevel(log_level_to_set)
try:
    mcp_file_handler = logging.handlers.RotatingFileHandler(
        settings.MCP_LOG_FILE, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    mcp_file_handler.setLevel(log_level_to_set)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s', '%Y-%m-%d %H:%M:%S')
    mcp_file_handler.setFormatter(file_formatter)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == mcp_file_handler.baseFilename for h in logging.getLogger().handlers):
        logging.getLogger().addHandler(mcp_file_handler)
    print(f"MCP логи будут записываться в файл: {settings.MCP_LOG_FILE} с уровнем {log_level_str}")
except Exception as e:
    print(f"Ошибка настройки файлового логгера для MCP: {e}")
if log_level_to_set > logging.DEBUG:
    for _logger_name in ["httpx", "httpcore", "uvicorn", "uvicorn.access", "uvicorn.error", "watchfiles"]:
        logging.getLogger(_logger_name).setLevel(logging.WARNING)
logger = logging.getLogger("app.main")

# --- Инициализация MCP сервера ---
mcp_server = FastMCP(
    name=settings.MCP_SERVER_NAME,
    instructions=settings.MCP_SERVER_INSTRUCTIONS,
)
logger.info(f"MCP Server '{settings.MCP_SERVER_NAME}' initialized.")

# --- Регистрация MCP инструментов ---
# Теперь мы явно создаем Tool объекты из функций
try:
    mcp_server.add_tool(Tool.from_function(exely_tools.get_hotel_public_info))
    mcp_server.add_tool(Tool.from_function(exely_tools.get_exely_booking_options))
    mcp_server.add_tool(Tool.from_function(exely_tools.create_exely_reservation_and_get_link))
    mcp_server.add_tool(Tool.from_function(exely_tools.cancel_exely_reservation))
    mcp_server.add_tool(Tool.from_function(exely_tools.process_natural_language_request))
    logger.info("MCP tools registered using Tool.from_function() and add_tool().")
except Exception as e_add_tool:
    logger.error(f"Error during mcp_server.add_tool: {e_add_tool}", exc_info=True)
    raise

# ... (остальная часть файла без изменений) ...
mcp_asgi_app = mcp_server.http_app(path="/mcp")
app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG_MODE, lifespan=mcp_asgi_app.lifespan)
logger.info(f"FastAPI app '{settings.APP_NAME}' initialized. Debug mode: {settings.DEBUG_MODE}, Log level: {log_level_str}")
app.mount("/mcp_api", mcp_asgi_app)
logger.info(f"FastMCP ASGI app mounted at /mcp_api. MCP endpoint available at /mcp_api/mcp")

@app.get("/")
async def root():
    logger.debug("Root endpoint '/' accessed.")
    return {"message": f"Welcome to {settings.APP_NAME}!", "mcp_endpoint": "/mcp_api/mcp", "docs": "/docs", "mcp_tools_openapi_via_inspector": "Run 'fastmcp dev app/main.py:mcp_server' and check inspector UI (usually at http://localhost:8765)"}
@app.get("/health")
async def health_check():
    logger.debug("Health check endpoint '/health' accessed.")
    return {"status": "ok"}

if __name__ == "__main__":
    logger.info("Starting Uvicorn server directly from app/main.py...")
    import uvicorn
    uvicorn_log_level = "warning"
    if log_level_to_set == logging.DEBUG: uvicorn_log_level = "debug"
    elif log_level_to_set == logging.INFO: uvicorn_log_level = "info"
    uvicorn.run("app.main:app", host=settings.MCP_SERVER_HOST, port=settings.MCP_SERVER_PORT, log_level=uvicorn_log_level, reload=settings.DEBUG_MODE)
