#!/bin/bash
set -e

# Create .local directory if it doesn't exist
LOCAL_DIR=".local"
if [ ! -d "$LOCAL_DIR" ]; then
    mkdir "$LOCAL_DIR"
fi

DEPLOY_INFO_FILE="$LOCAL_DIR/deploy_info"

# If deployment info exists, load and ask for confirmation; otherwise, prompt the user.
if [ -f "$DEPLOY_INFO_FILE" ]; then
    source "$DEPLOY_INFO_FILE"
    echo "Stored Resource Group: $RESOURCE_GROUP"
    echo "Stored App Service Name: $APP_SERVICE"
    read -p "Do you want to use these values? (Y/n): " confirm
    if [[ "$confirm" =~ ^([nN])$ ]]; then
        read -p "Enter Resource Group Name: " RESOURCE_GROUP
        read -p "Enter App Service Name: " APP_SERVICE
        echo "RESOURCE_GROUP=$RESOURCE_GROUP" > "$DEPLOY_INFO_FILE"
        echo "APP_SERVICE=$APP_SERVICE" >> "$DEPLOY_INFO_FILE"
    fi
else
    read -p "Enter Resource Group Name: " RESOURCE_GROUP
    read -p "Enter App Service Name: " APP_SERVICE
    echo "RESOURCE_GROUP=$RESOURCE_GROUP" > "$DEPLOY_INFO_FILE"
    echo "APP_SERVICE=$APP_SERVICE" >> "$DEPLOY_INFO_FILE"
fi

# Delete existing deployment.zip if it exists
if [ -f deployment.zip ]; then
    rm deployment.zip
fi

# Create deployment zip including:
# - requirements.txt
# - All .py files in the root
# - The static folder and its contents
zip -r deployment.zip requirements.txt *.py static

# Deploy using Azure CLI (uncomment the next line to enable deployment)
az webapp deployment source config-zip --resource-group "$RESOURCE_GROUP" --name "$APP_SERVICE" --src deployment.zip

# echo "Deployment complete."
# echo ""
# echo "Reminder:"
# echo "1) Add the environment variables listed in README.md."
# echo "2) Set the Startup Command in the App Service settings:"
# echo "   python -m uvicorn main:app --host=0.0.0.0 --port=$PORT"
