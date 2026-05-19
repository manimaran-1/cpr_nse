#!/bin/bash

# --- NSE STOCK SCANNER v2.0 LOCAL RUNNER ---
# Automates environment setup and project launching.

# Get the directory where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "========================================"
echo "   NSE Stock Scanner v2.0 Local Runner  "
echo "========================================"

# 1. Virtual Environment Setup
if [ ! -d "venv" ]; then
    echo "🏗️  Creating new virtual environment (venv)..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌ Error: Failed to create virtual environment. Please install python3-venv."
        exit 1
    fi
fi

# 2. Activate Environment and Install Requirements
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Use a marker file to skip pip install if already done (faster launch)
if [ ! -f "venv/.installed" ] || [ "requirements.txt" -nt "venv/.installed" ]; then
    echo "📦 Installing/Updating dependencies... (this may take a minute)"
    pip install --upgrade pip
    pip install -r requirements.txt
    if [ $? -eq 0 ]; then
        touch venv/.installed
    else
        echo "❌ Error: Failed to install requirements."
        exit 1
    fi
fi

# 3. Load Environment Variables from .env
if [ -f ".env" ]; then
    echo "🔑 Loading environment variables from .env..."
    # Safely source .env while handling spaces and quotes
    set -a
    source .env
    set +a
else
    echo "⚠️  Warning: .env file not found. Ensure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."
fi

# 4. Interactive Launch Menu Loop
select_data_source() {
    echo ""
    echo "📡 Select Data Source:"
    echo "----------------------------------------"
    echo "1) Yahoo Finance Direct API"
    echo "2) yfinance Library"
    echo "----------------------------------------"
    read -p "Enter Choice [1-2] (default=1): " DSChoice
    case $DSChoice in
        2) export DATA_SOURCE="yfinance" ;;
        *) export DATA_SOURCE="yahoo" ;;
    esac
    echo "📡 Data source: $DATA_SOURCE"
}

while true; do
    echo ""
    echo "Select an option to run:"
    echo "----------------------------------------"
    echo "1) 📊  Launch Streamlit Dashboard (Localhost)"
    echo "2) 🤖  Run Automation Bot (Scheduled Scans)"
    echo "3) 🚀  Run a Quick Test Scan (Manual Trigger)"
    echo "4) 🚪  Exit"
    echo "----------------------------------------"
    read -p "Enter Choice [1-4]: " Choice

    case $Choice in
        1)
            select_data_source
            echo "🚀 Starting Streamlit Dashboard..."
            streamlit run app.py
            ;;
        2)
            select_data_source
            echo "🚀 Starting Automation Bot..."
            python3 automation_bot.py
            ;;
        3)
            select_data_source
            echo "🚀 Triggering Manual Test Scan..."
            export TEST_RUN=1
            export ONCE=1
            python3 automation_bot.py
            echo ""
            echo "✅ Manual scan execution complete."
            read -p "Press Enter to return to menu..." dummy
            ;;
        4)
            echo "👋 Exiting."
            exit 0
            ;;
        *)
            echo "❌ Invalid choice. Please try again."
            sleep 1
            ;;
    esac
done
