<p align="right">Read this in other languages: <a href="./README.ru.md">Русский (Russian)</a></p>

# Exely Hotel Booking MCP Assistant

A project to integrate the Exely Distribution API with an LLM via an MCP server, allowing interaction through a Telegram bot.

This project is containerized with Docker for easy and reliable deployment in a production environment on any server or VPS.

### Key Features
- **One-Click Deployment**: Use the `deploy.sh` (for Linux) or `deploy.ps1` (for Windows) scripts for automatic installation and setup.
- **Interactive Setup**: The scripts will prompt you for the necessary API keys and create the configuration files for you.
- **Flexible**: You can deploy all components on a single machine or split the MCP server and Telegram bot across different servers.
- **Production-Ready**: Uses a Multistage Docker build to create lightweight and secure images.
- **Reliable**: Containers are configured to restart automatically in case of failure.

## Project structure

```
exely_mcp_project/
├── app/                      # Application source code (FastAPI/MCP server)
│   ├── __init__.py
│   ├── config.py             # Application configuration (reads from .env files)
│   ├── main.py               # FastAPI entrypoint with the MCP server
│   ├── exely_client/         # Client for the Exely API
│   │   ├── __init__.py
│   │   ├── client.py         # The API client itself
│   │   └── schemas.py        # Pydantic models for the Exely API
│   ├── llm_client/           # Client for the Mistral LLM API
│   │   ├── __init__.py
│   │   └── llm_client.py
│   └── mcp_tools/            # MCP tools for the LLM
│       ├── __init__.py
│       ├── schemas_llm.py    # Pydantic models for tool parameters
│       ├── tools.py          # Tool implementation logic
│       └── prompt_utils.py   # Utilities for generating prompts
│
├── telegram_bot.py           # Telegram bot source code
├── pyproject.toml            # Project dependencies and metadata
│
├── README.md                 # Main documentation (English)
├── README.ru.md              # Optional documentation (Russian)
│
│   --- Deployment Files ---
├── deploy.sh                 # Deployment script for Linux/macOS
├── deploy.ps1                # Deployment script for Windows (PowerShell)
├── Dockerfile                # Instructions for building the Docker image
├── .dockerignore             # Specifies files to exclude from the image
├── docker-compose.yml        # Docker Compose for all-in-one deployment
├── docker-compose.server.yml # For deploying the server only
├── docker-compose.bot.yml    # For deploying the bot only
│
│   --- Environment Files (usually not in git) ---
├── .env.prod                 # (Generated) Production environment variables
├── .env.bot.prod             # (Generated) Env vars for a remote bot
└── .env.example              # Template for local development (without Docker)
```


## Deployment (Production)

This is the recommended method for running the project on a VPS or any other server.

### Prerequisites
- **Git** to clone the repository.
- **Docker and Docker Compose**: The deployment script will attempt to automatically install them on Ubuntu systems. For other operating systems, please install them according to the official documentation.

### Launch Instructions

1.  **Clone the repository to your server:**
    ```bash
    git clone https://github.com/Bdata0/Exely_MCP.git
    cd ~/Exely_MCP
    ```

2.  **Run the deployment script:**
    The script will check for Docker, prompt you for all required API keys and tokens, create the configuration files, and launch the project.

    *   **For Linux (Ubuntu, Debian, etc.):**
        First, make the script executable:
        ```bash
        chmod +x deploy.sh
        ```
        Then, run it:
        ```bash
        ./deploy.sh
        ```

    *   **For Windows (using PowerShell):**
        You may need to allow script execution for the current session:
        ```powershell
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
        ```
        Then, run the script:
        ```powershell
        .\deploy.ps1
        ```

3.  **Follow the on-screen instructions:**
    *   The script will ask you to enter your `EXELY_API_KEY`, `MISTRAL_API_KEY`, and `TELEGRAM_BOT_TOKEN`. Input will be hidden for security.
    *   Next, it will prompt you to choose a deployment scenario:
        1.  **All-in-one**: Run both the server and the bot on the current machine (most common choice).
        2.  **Server only**: Run only the MCP server.
        3.  **Bot only**: Run only the Telegram bot (will require the IP address of the server machine).

After selecting a scenario, the script will automatically build the Docker images and start the containers in the background.

### Application Management

-   **Check container status:** `docker compose ps`
-   **View real-time logs:** `docker compose logs -f`
-   **Stop the application:** `docker compose down`

Your bot is now fully configured and running!
