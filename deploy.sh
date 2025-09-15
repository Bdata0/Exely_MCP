#!/bin/bash

# deploy.sh
# Script to deploy the Exely MCP Assistant project using Docker.
set -e

# --- Colors for output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Functions ---
command_exists() {
    command -v "$1" &> /dev/null
}

docker_is_accessible() {
    docker info &> /dev/null 2>&1
}

restart_script_with_docker_access() {
    echo -e "${YELLOW}Restarting script with Docker access...${NC}"
    sleep 2
    # Use sg command to run the script in docker group context
    exec sg docker "$0 $*"
}

create_or_update_main_env() {
    echo -e "${YELLOW}Please enter your production API keys. Input will be hidden.${NC}"
    echo -n "Enter EXELY_API_KEY: "
    read -s EXELY_KEY; echo
    echo -n "Enter MISTRAL_API_KEY: "
    read -s MISTRAL_KEY; echo
    echo -n "Enter TELEGRAM_BOT_TOKEN: "
    read -s TELEGRAM_BOT_KEY; echo

    echo "Creating/updating .env.prod file..."
    cat <<EOF > .env.prod
EXELY_API_KEY="${EXELY_KEY}"
MISTRAL_API_KEY="${MISTRAL_KEY}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_KEY}"
DEFAULT_HOTEL_CODE="508308"
DEBUG_MODE=False
MCP_SERVER_PORT=8000
MCP_SERVER_HOST="0.0.0.0"
LLM_MODEL_NAME="mistral-small-latest"
EOF
    echo -e "${GREEN}.env.prod file successfully created/updated.${NC}"
}

create_or_update_bot_env() {
    echo -e "${YELLOW}Configuring .env.bot.prod for a remote bot...${NC}"
    echo -n "Enter TELEGRAM_BOT_TOKEN (input will be hidden): "
    read -s BOT_ONLY_TOKEN; echo
    echo -n "Enter MISTRAL_API_KEY (needed for bot startup, input hidden): "
    read -s BOT_MISTRAL_KEY; echo
    echo -n "Enter the public IP address or domain of the MCP_SERVER: "
    read SERVER_HOST_IP

    echo "Creating/updating .env.bot.prod file..."
    cat <<EOF > .env.bot.prod
TELEGRAM_BOT_TOKEN="${BOT_ONLY_TOKEN}"
MISTRAL_API_KEY="${BOT_MISTRAL_KEY}"
MCP_SERVER_HOST="${SERVER_HOST_IP}"
MCP_SERVER_PORT=8000
EOF
    echo -e "${GREEN}.env.bot.prod successfully created/updated.${NC}"
}

# --- Step 1: Check and Install Docker ---
echo -e "${GREEN}Step 1: Checking and Installing Docker...${NC}"
if ! command_exists docker; then
    echo -e "${YELLOW}Docker not found. Installing Docker...${NC}"
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER"
    echo -e "${GREEN}Docker successfully installed.${NC}"

    # Start Docker service if not running
    sudo systemctl start docker
    sudo systemctl enable docker

    echo -e "${YELLOW}Docker installed. Restarting script with proper permissions...${NC}"
    restart_script_with_docker_access "$@"
else
    echo -e "${GREEN}Docker command is available.${NC}"
fi

# --- Step 1.5: Verify Docker Access ---
echo -e "${GREEN}Verifying Docker access...${NC}"
if ! docker_is_accessible; then
    echo -e "${YELLOW}Docker daemon not accessible. Checking permissions...${NC}"

    # Check if user is in docker group
    if groups "$USER" | grep -q docker; then
        echo -e "${YELLOW}User is in docker group but permissions not applied in current session.${NC}"
        echo -e "${YELLOW}Restarting script with proper group permissions...${NC}"
        restart_script_with_docker_access "$@"
    else
        echo -e "${YELLOW}Adding user to docker group...${NC}"
        sudo usermod -aG docker "$USER"
        echo -e "${YELLOW}User added to docker group. Restarting script...${NC}"
        restart_script_with_docker_access "$@"
    fi
else
    echo -e "${GREEN}Docker is accessible and working.${NC}"
fi

# --- Step 2: Prepare Environment ---
echo -e "\n${GREEN}Step 2: Preparing environment and log files...${NC}"
touch mcp_log.txt telegram_bot_log.txt

# --- Step 3: Build and Run ---
echo -e "\n${GREEN}Step 3: Selecting scenario and running Docker containers...${NC}"
echo "Which deployment scenario would you like to use?"
echo "1) All-in-one (MCP server and Telegram bot on this machine)"
echo "2) Server only (Deploy only the MCP server on this machine)"
echo "3) Bot only (Deploy only the Telegram bot on this machine)"
read -p "Enter the number (1/2/3): " choice

case $choice in
    1)
        if [ ! -f .env.prod ]; then
            create_or_update_main_env
        else
            read -p ".env.prod already exists. Overwrite? (y/n): " ow
            if [[ "$ow" == [yY] ]]; then
                create_or_update_main_env
            fi
        fi
        echo -e "${GREEN}Starting both services...${NC}"
        docker compose -f docker-compose.yml build && docker compose -f docker-compose.yml up -d
        ;;
    2)
        if [ ! -f .env.prod ]; then
            create_or_update_main_env
        else
            read -p ".env.prod already exists. Overwrite? (y/n): " ow
            if [[ "$ow" == [yY] ]]; then
                create_or_update_main_env
            fi
        fi
        echo -e "${GREEN}Starting the MCP server only...${NC}"
        docker compose -f docker-compose.server.yml build && docker compose -f docker-compose.server.yml up -d
        ;;
    3)
        if [ ! -f .env.bot.prod ]; then
            create_or_update_bot_env
        else
            read -p ".env.bot.prod already exists. Overwrite? (y/n): " ow
            if [[ "$ow" == [yY] ]]; then
                create_or_update_bot_env
            fi
        fi
        echo -e "${GREEN}Starting the Telegram bot only...${NC}"
        docker compose -f docker-compose.bot.yml build && docker compose -f docker-compose.bot.yml up -d
        ;;
    *)
        echo -e "${RED}Invalid choice. Aborting.${NC}"
        exit 1
        ;;
esac

echo -e "\n${GREEN}Done! The project has been successfully deployed.${NC}"
echo -e "\n${YELLOW}Useful commands:${NC}"
echo -e "Check container status: ${GREEN}docker compose ps${NC}"
echo -e "View logs:             ${GREEN}docker compose logs -f${NC}"
echo -e "Stop services:         ${GREEN}docker compose down${NC}"
