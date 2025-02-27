# Set strict error handling
$ErrorActionPreference = "Stop"

# Create .local directory if it doesn't exist
$LOCAL_DIR = ".local"
if (-Not (Test-Path $LOCAL_DIR)) {
    New-Item -ItemType Directory -Path $LOCAL_DIR | Out-Null
}

$DEPLOY_INFO_FILE = Join-Path $LOCAL_DIR "deploy_info"

# If deployment info exists, load it and ask for confirmation; otherwise, prompt the user.
if (Test-Path $DEPLOY_INFO_FILE) {
    $content = Get-Content $DEPLOY_INFO_FILE
    foreach ($line in $content) {
        if ($line -match "^RESOURCE_GROUP=(.*)$") {
            $RESOURCE_GROUP = $matches[1]
        }
        elseif ($line -match "^APP_SERVICE=(.*)$") {
            $APP_SERVICE = $matches[1]
        }
    }
    Write-Host "Stored Resource Group: $RESOURCE_GROUP"
    Write-Host "Stored App Service Name: $APP_SERVICE"
    $confirm = Read-Host "Do you want to use these values? (Y/n)"
    if ($confirm -match "^[nN]$") {
        $RESOURCE_GROUP = Read-Host "Enter Resource Group Name"
        $APP_SERVICE = Read-Host "Enter App Service Name"
        "RESOURCE_GROUP=$RESOURCE_GROUP" | Out-File -FilePath $DEPLOY_INFO_FILE -Encoding utf8
        "APP_SERVICE=$APP_SERVICE" | Add-Content -Path $DEPLOY_INFO_FILE
    }
}
else {
    $RESOURCE_GROUP = Read-Host "Enter Resource Group Name"
    $APP_SERVICE = Read-Host "Enter App Service Name"
    "RESOURCE_GROUP=$RESOURCE_GROUP" | Out-File -FilePath $DEPLOY_INFO_FILE -Encoding utf8
    "APP_SERVICE=$APP_SERVICE" | Add-Content -Path $DEPLOY_INFO_FILE
}

# Delete existing deployment.zip if it exists
if (Test-Path "deployment.zip") {
    Remove-Item "deployment.zip"
}

# Create deployment zip including:
# - requirements.txt
# - All .py files in the root
# - The static folder and its contents
Compress-Archive -Path "requirements.txt", "*.py", "static" -DestinationPath "deployment.zip"

# Deploy using Azure CLI (uncomment the next line to enable deployment)
az webapp deployment source config-zip --resource-group $RESOURCE_GROUP --name $APP_SERVICE --src deployment.zip

<# 
Write-Host "Deployment complete."
Write-Host ""
Write-Host "Reminder:"
Write-Host "1) Add the environment variables listed in README.md."
Write-Host "2) Set the Startup Command in the App Service settings:"
Write-Host "   python -m uvicorn main:app --host=0.0.0.0 --port=$PORT"
#>
