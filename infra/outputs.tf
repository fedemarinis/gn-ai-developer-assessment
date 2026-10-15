output "api_url" {
  description = "Public HTTPS URL of the ticketing API (interactive docs at <api_url>/docs)."
  value       = "https://${azurerm_linux_web_app.api.default_hostname}"
}

output "resource_group_name" {
  description = "Name of the resource group that holds all resources."
  value       = azurerm_resource_group.main.name
}

output "web_app_name" {
  description = "Name of the web app, needed to deploy code (e.g. `az webapp up` or zip deploy)."
  value       = azurerm_linux_web_app.api.name
}
