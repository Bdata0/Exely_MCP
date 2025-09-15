# deploy.ps1
# PowerShell script to deploy the Exely MCP Assistant project using Docker.
$ErrorActionPreference = "Stop"

function Test-CommandExists { param($command) { return (Get-Command $command -ErrorAction SilentlyContinue) } }
function New-MainEnvFile {
    Write-Host "`nPlease enter your production API keys." -ForegroundColor Yellow
    $exelyKey = Read-Host -Prompt "Enter EXELY_API_KEY" -AsSecureString
    $mistralKey = Read-Host -Prompt "Enter MISTRAL_API_KEY" -AsSecureString
    $telegramBotKey = Read-Host -Prompt "Enter TELEGRAM_BOT_TOKEN" -AsSecureString

    $ExelyPlainText = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($exelyKey))
    $MistralPlainText = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($mistralKey))
    $TelegramPlainText = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($telegramBotKey))

    Write-Host "`nCreating/updating .env.prod file..."
    $envContent = "EXELY_API_KEY=`"$ExelyPlainText`"`nMISTRAL_API_KEY=`"$MistralPlainText`"`nTELEGRAM_BOT_TOKEN=`"$TelegramPlainText`"`n`nDEFAULT_HOTEL_CODE=`"508308`"`nDEBUG_MODE=False`nMCP_SERVER_PORT=8000`nMCP_SERVER_HOST=`"0.0.0.0`"`nLLM_MODEL_NAME=`"mistral-small-latest`""
    Set-Content -Path ".env.prod" -Value $envContent
    Write-Host ".env.prod file successfully created/updated." -ForegroundColor Green
}
function New-BotEnvFile {
    Write-Host "`nConfiguring .env.bot.prod for a remote bot..." -ForegroundColor Yellow
    $botToken = Read-Host -Prompt "Enter TELEGRAM_BOT_TOKEN" -AsSecureString
    $serverHost = Read-Host -Prompt "Enter the public IP address or domain of the MCP_SERVER"
    $BotTokenPlainText = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($botToken))
    Write-Host "`nCreating/updating .env.bot.prod file..."
    $envContent = "TELEGRAM_BOT_TOKEN=`"$BotTokenPlainText`"`nMCP_SERVER_HOST=`"$serverHost`"`nMCP_SERVER_PORT=8000"
    Set-Content -Path ".env.bot.prod" -Value $envContent
    Write-Host ".env.bot.prod successfully created/updated." -ForegroundColor Green
}

Write-Host "`nStep 1: Checking for Docker..." -ForegroundColor Green
    if (-not (Test-CommandExists docker)) {
        Write-Host "Docker is not installed. Please install Docker Desktop and re-run." -ForegroundColor Yellow
        exit 1
    } else {
        Write-Host "Docker is installed." -ForegroundColor Green
    }

    try {
        docker compose version | Out-Null
        Write-Host "Docker Compose is available." -ForegroundColor Green
    } catch {
        Write-Host "Docker Compose V2 is not available or not working correctly. Please ensure Docker Desktop is running and up to date." -ForegroundColor Yellow
        exit 1
    }

Write-Host "`nStep 2: Preparing environment..." -ForegroundColor Green
if (-not (Test-Path "mcp_log.txt")) { New-Item -ItemType File "mcp_log.txt" | Out-Null }
if (-not (Test-Path "telegram_bot_log.txt")) { New-Item -ItemType File "telegram_bot_log.txt" | Out-Null }

Write-Host "`nStep 3: Selecting scenario..." -ForegroundColor Green
Write-Host "1) All-in-one" "2) Server only" "3) Bot only"
$choice = Read-Host -Prompt "Enter number (1/2/3)"

switch ($choice) {
    "1" {
        if (-not (Test-Path ".env.prod")) { New-MainEnvFile } else { $ow = Read-Host ".env.prod exists. Overwrite? (y/n)"; if ($ow -eq 'y') { New-MainEnvFile } }
        Write-Host "Starting both services..." -ForegroundColor Green
        docker compose -f docker-compose.yml build; docker compose -f docker-compose.yml up -d
    }
    "2" {
        if (-not (Test-Path ".env.prod")) { New-MainEnvFile } else { $ow = Read-Host ".env.prod exists. Overwrite? (y/n)"; if ($ow -eq 'y') { New-MainEnvFile } }
        Write-Host "Starting server only..." -ForegroundColor Green
        docker compose -f docker-compose.server.yml build; docker compose -f docker-compose.server.yml up -d
    }
    "3" {
        if (-not (Test-Path ".env.bot.prod")) { New-BotEnvFile } else { $ow = Read-Host ".env.bot.prod exists. Overwrite? (y/n)"; if ($ow -eq 'y') { New-BotEnvFile } }
        Write-Host "Starting bot only..." -ForegroundColor Green
        docker compose -f docker-compose.bot.yml build; docker compose -f docker-compose.bot.yml up -d
    }
    default { Write-Host "Invalid choice. Aborting." -ForegroundColor Red; exit 1 }
}

Write-Host "`nDone! Project deployed." -ForegroundColor Green
