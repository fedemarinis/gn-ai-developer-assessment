# Minimal Azure hosting for the Part 1 Mock Ticketing API.
# Three resources: resource group -> Linux App Service plan -> Linux web app.
# App Service runs the Python code directly, so no container image or registry
# is needed. Skeleton only: checked with `terraform validate`, not deployed.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

# AzureRM v4 requires an explicit Azure subscription ID for plan and apply.
# Supply it through the ARM_SUBSCRIPTION_ID environment variable; signing in
# with `az login` alone is not sufficient. The ID is kept out of the code.
provider "azurerm" {
  features {}
}

# 1. Resource group: holds all resources so they can be managed and deleted together.
resource "azurerm_resource_group" "main" {
  name     = "rg-${var.project_name}"
  location = var.location
  tags     = var.tags
}

# 2. App Service plan: the Linux compute (size and price tier) that hosts the web app.
resource "azurerm_service_plan" "main" {
  name                = "asp-${var.project_name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = var.sku_name
  tags                = var.tags
}

# 3. Linux web app: runs the FastAPI app on the built-in Python runtime.
resource "azurerm_linux_web_app" "api" {
  name                = "${var.project_name}-api" # must be globally unique: <name>.azurewebsites.net
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_service_plan.main.location
  service_plan_id     = azurerm_service_plan.main.id
  https_only          = true
  tags                = var.tags

  site_config {
    always_on = true # keeps the single in-memory process running; not available on F1 (Free)

    # One Uvicorn worker: tickets are stored in memory, so a second process
    # would have its own, different copy of the data.
    app_command_line = "python -m uvicorn ticket_api.main:app --host 0.0.0.0 --port 8000"

    application_stack {
      python_version = var.python_version
    }
  }

  app_settings = {
    # Run `pip install -r requirements.txt` on the server during a code deploy.
    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "true"
  }
}
