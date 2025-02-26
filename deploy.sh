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

# Build exclude patterns from .gitignore (ignoring empty lines and comments)
EXCLUDES=()
if [ -f ".gitignore" ]; then
    while IFS= read -r line; do
        # Trim whitespace
        pattern=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        # Skip blank lines or comments
        if [ -z "$pattern" ] || [[ "$pattern" =~ ^# ]]; then
            continue
        fi
        EXCLUDES+=("-x" "$pattern")
    done < .gitignore
fi

# Create deployment zip excluding files/folders from .gitignore
zip -r deployment.zip . "${EXCLUDES[@]}"

# Deploy using Azure CLI
az webapp deployment source config-zip --resource-group "$RESOURCE_GROUP" --name "$APP_SERVICE" --src deployment.zip

echo "Deployment complete."
echo ""
echo "Reminder:"
echo "1) Add the environment variables listed in README.md."
echo "2) Set the Startup Command in the App Service settings:"
echo "   uvicorn main:app --host=0.0.0.0 --port=\$PORT"
