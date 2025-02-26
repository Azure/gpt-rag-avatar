# Enterprise RAG Avatar

Part of [GPT-RAG](https://aka.ms/gpt-rag)

**GPT-RAG Avatar** is an interactive FastAPI-based application that brings together GenAI-powered responses, voice recognition, and text-to-speech capabilities using Azure services. The project leverages Azure App Service for hosting, Azure Key Vault, and Azure Speech Service for voice interactions. 

![Avatar Screenshot](media/avatar.png)
---

## Table of Contents

1. [Concepts](#concepts)
2. [Prerequisites](#prerequisites)
3. [Deployment to Azure App Service](#deployment-to-azure-app-service)
4. [Running Locally](#running-locally)
5. [Environment Variables](#environment-variables)
6. [Azure Key Vault Secrets](#azure-key-vault-secrets)

---

## Concepts

**Enterprise RAG Avatar** is an interactive FastAPI application that harnesses:
- **GenAI-Powered Responses:** Delivers intelligent, context-aware answers.
- **Voice Interaction:** Integrates Azure Speech API for both speech recognition and text-to-speech.
- **Secure Secret Management:** Uses Azure Key Vault to safeguard sensitive credentials.
- **Optional MSAL Authentication:** Enables secure user sign-in.
- **Streaming Support:** Leverages an agentic orchestrator that supports real-time streaming responses.

This solution is designed for enterprises looking to build engaging conversational experiences with a customizable avatar interface.

---

## Prerequisites

- **Python 3.12**
- **Azure CLI:** Ensure you are logged in with az login.
- An **Azure App Service** and **App Service Plan**.
- An **Azure Speech Services** in a region where avatar feature is supported.
- An **Azure Key Vault** with the required secrets configured.

> [!IMPORTANT]
> Avatar uses gpt-rag agentic orchestrator, that supports streaming used in real-time voice interactions.

> [!NOTE]
> When deploying to the cloud, you can use the same GPT-RAG web front-end App Service. However, if you wish to run both the front-end and the avatar as separate services, provision a new App Service based on the Python runtime.

---

## Deployment to Azure App Service

Follow these steps to deploy your application using the provided scripts.

### 1. Choose and Run Your Deployment Script

We provide two scripts to automate packaging and deployment while excluding unwanted files (`.gitignore` rules apply):

- **Bash (`deploy.sh`)** – For Linux/macOS.  
  Run:
  ```bash
  deploy.sh && ./deploy.sh
  ```

- **PowerShell (`deploy.ps1`)** – For Windows.  
  Run:
  ```powershell
  PowerShell -ExecutionPolicy Bypass -File .\deploy.ps1
  ```

Both scripts:
- Store deployment settings (`Resource Group`, `App Service Name`) in `.local`.
- Package the project into `deployment.zip`, excluding unnecessary files.
- Deploy using Azure CLI.
- Remind you to add environment variables and set the startup command.

### 2. Configure App Settings in Azure

After deployment, complete these steps in the [Azure Portal](https://portal.azure.com):

- **Set Environment Variables:**  
  - Navigate to your App Service → **Configuration** → **Application Settings**.
  - Add variables as listed in [Environment Variables](#environment-variables).

- **Set the Startup Command:**  
  ```bash
  uvicorn main:app --host=0.0.0.0 --port=$PORT
  ```
  Save and restart if needed.

- **Set Secrets:**  
  - Navigate to GPT-RAG's KEyVault.
  - Add secrets as listed in [Azure Key Vault Secrets](#azure-key-vault-secrets).

---

## Running Locally

1. **Clone the Repository:**

   ```bash
   git clone https://your-repo-url.git
   cd gpt-rag-avatar
   ```

2. **Creating Your Environment**

   You can use either Python's built-in `venv` or Conda:

   ### Using venv

   ```bash
   python -m venv venv
   source venv/bin/activate   # On Windows use: venv\Scripts\activate
   pip install -r requirements.txt
   ```

   ### Using Conda

   ```bash
   conda create -n gpt-rag-avatar python=3.12
   conda activate gpt-rag-avatar
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**

   Copy the provided template to create your own configuration file:

   ```bash
   cp .env.template .env
   ```

   Then, edit `.env` with your specific settings.

4. **Set Up Environment Variables:**

   Ensure your `.env` file is correctly configured.

5. **Run the Application:**

   ```bash
   uvicorn main:app --reload
   ```

   Access the app at [http://localhost:8000](http://localhost:8000).


---

## Environment Variables

Set the following environment variables in your `.env` file (or via the App Service's Application Settings).

### General
- **AZURE_KEY_VAULT_NAME:** Your Azure Key Vault name.
- **PORT:** Port on which the FastAPI server runs (default: `8000`).

### Authentication
- **ENABLE_AUTHENTICATION:** `"true"` to enable MSAL-based authentication; otherwise `"false"` (default: `"false"`).
- **CLIENT_ID:** The Azure AD Application (Client) ID.
- **AUTHORITY:** The authority URL (default: `https://login.microsoftonline.com/your_tenant_id`).
- **REDIRECT_PATH:** The authentication redirect path (default: `/getAToken`).
- **REDIRECT_URI:** The full redirect URI (e.g., `http://localhost:8000/getAToken`).
- **OTHER_AUTH_SCOPES:** (Optional) Comma-separated list of additional Azure scopes.
- **APP_SERVICE_CLIENT_SECRET_NAME:** Key Vault secret storing the MSAL client secret (default: `appServiceClientSecretKey`).

### Azure Speech API
- **AZURE_SPEECH_REGION:** The region for your Azure Speech API (default: `eastus2`).
- **SUPPORTED_LANGUAGES:** Comma-separated list of supported languages (default: `en-US,de-DE,zh-CN,nl-NL`).

### Orchestrator
- **STREAMING_ENDPOINT:** URL endpoint for the orchestrator’s streaming API (default: `http://localhost:7071/api/orcstream`).

> [!TIP]
> For your convenience, we provide a JSON file [env_vars_template.json](docs/env_vars_template.json) that you can update and copy-paste directly into the "Advanced edit" option on the Environment Variables page of your App Service. 


---

## Azure Key Vault Secrets

For secure operation, create the following secrets in your Azure Key Vault:

- **avatarSessionSecretKey:** The secret key used for session management.
- **avatarOrchestratorFunctionKey:** The function key required to access the orchestrator service.
- **avatarSpeechApiKey:** Your Azure Speech API key.
- **avatarMsalClientSecret:** The MSAL client secret for authentication.

Also, ensure that the App Service's managed identity is granted permission to get these secrets from the Key Vault.   