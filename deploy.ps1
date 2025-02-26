# deploy.ps1
# Run with: PowerShell -ExecutionPolicy Bypass -File .\deploy.ps1

# Stop on error
$ErrorActionPreference = 'Stop'

# Ensure .local directory exists
$localDir = ".local"
if (-not (Test-Path $localDir)) {
    New-Item -ItemType Directory -Path $localDir | Out-Null
}

$deployInfoFile = Join-Path $localDir "deploy_info.ps1"

# Function to prompt for deployment info and save it
function Get-DeploymentInfo {
    $resourceGroup = Read-Host "Enter Resource Group Name"
    $appService = Read-Host "Enter App Service Name"
    $content = "`$RESOURCE_GROUP = '$resourceGroup'`n`$APP_SERVICE = '$appService'"
    Set-Content -Path $deployInfoFile -Value $content
    return @{ RESOURCE_GROUP = $resourceGroup; APP_SERVICE = $appService }
}

# Load stored info if available and confirm with the user
if (Test-Path $deployInfoFile) {
    . $deployInfoFile
    Write-Host "Stored Resource Group: $RESOURCE_GROUP"
    Write-Host "Stored App Service Name: $APP_SERVICE"
    $confirm = Read-Host "Do you want to use these values? (Y/n)"
    if ($confirm -eq "n") {
        $info = Get-DeploymentInfo
        $RESOURCE_GROUP = $info.RESOURCE_GROUP
        $APP_SERVICE = $info.APP_SERVICE
    }
} else {
    $info = Get-DeploymentInfo
    $RESOURCE_GROUP = $info.RESOURCE_GROUP
    $APP_SERVICE = $info.APP_SERVICE
}

# Read .gitignore (if exists) and build exclusion patterns.
# Also add default exclusions: venv/* and .env
$excludePatterns = @()
if (Test-Path ".gitignore") {
    $gitignoreLines = Get-Content ".gitignore" | ForEach-Object { $_.Trim() } | Where-Object { $_ -and ($_ -notmatch '^\s*#') }
    $excludePatterns += $gitignoreLines
}
$excludePatterns += @("venv/*", ".env")
# Remove duplicate patterns
$excludePatterns = $excludePatterns | Select-Object -Unique

# Function: check if a relative path should be excluded based on patterns.
function ShouldExclude($relativePath, $patterns) {
    # Normalize path to use forward slashes
    $normPath = $relativePath -replace '\\','/'
    foreach ($pattern in $patterns) {
        # Use -like for wildcard matching.
        if ($normPath -like $pattern) {
            return $true
        }
    }
    return $false
}

# Get the current directory path (root for zipping)
$rootPath = (Get-Location).Path

# Collect all files recursively that are NOT excluded.
$filesToInclude = Get-ChildItem -Recurse -File | ForEach-Object {
    # Compute relative path
    $relativePath = $_.FullName.Substring($rootPath.Length + 1)
    if (-not (ShouldExclude $relativePath $excludePatterns)) {
        # Return the relative path (preserving folder structure)
        $relativePath
    }
} | Where-Object { $_ }

# Create a temporary file list for Compress-Archive
$tempListFile = [System.IO.Path]::GetTempFileName()
$tempListFilePath = "$tempListFile.txt"
# Write the list of relative file paths
$filesToInclude | Out-File -FilePath $tempListFilePath -Encoding UTF8

# Compress-Archive does not support an exclude parameter.
# So we use -RootPath with a custom list.
# If there are no files to include, abort.
if ($filesToInclude.Count -eq 0) {
    Write-Error "No files to include in the deployment package."
    exit 1
}

# Compress-Archive: To preserve directory structure, we specify the root as the current directory
# and supply the list of files (relative paths) to include.
Compress-Archive -RootPath $rootPath -Path $filesToInclude -DestinationPath "deployment.zip" -Force

# Remove temporary file list
Remove-Item $tempListFilePath -Force

# Deploy using Azure CLI
$deployCommand = "az webapp deployment source config-zip --resource-group `"$RESOURCE_GROUP`" --name `"$APP_SERVICE`" --src deployment.zip"
Write-Host "Running deployment command:"
Write-Host $deployCommand
Invoke-Expression $deployCommand

Write-Host "`nDeployment complete."
Write-Host "`nReminder:"
Write-Host "1) Add the environment variables listed in README.md."
Write-Host "2) Set the Startup Command in the App Service settings:"
Write-Host "   uvicorn main:app --host=0.0.0.0 --port=`$PORT"
