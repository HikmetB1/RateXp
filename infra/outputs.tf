output "resource_group" {
  description = "Resource group holding everything."
  value       = azurerm_resource_group.this.name
}

output "acr_name" {
  description = "ACR name (use with `az acr login --name <this>`)."
  value       = azurerm_container_registry.this.name
}

output "acr_login_server" {
  description = "ACR registry hostname."
  value       = azurerm_container_registry.this.login_server
}

output "core_image" {
  description = "Build & push this image, then restart the core web app."
  value       = "${azurerm_container_registry.this.login_server}/core:${var.image_tag}"
}

output "app_image" {
  description = "Build & push this image, then restart the app web app."
  value       = "${azurerm_container_registry.this.login_server}/app:${var.image_tag}"
}

output "core_name" {
  description = "core web app name (use with `az webapp restart`)."
  value       = azurerm_linux_web_app.core.name
}

output "app_name" {
  description = "app web app name (use with `az webapp restart`)."
  value       = azurerm_linux_web_app.app.name
}

output "core_url" {
  description = "Public URL of core - point your skills' .mcp.json here (append /mcp)."
  value       = local.core_url
}

output "app_url" {
  description = "Public URL of the dashboard."
  value       = local.app_url
}

output "postgres_fqdn" {
  description = "PostgreSQL server hostname."
  value       = azurerm_postgresql_flexible_server.this.fqdn
}

output "core_identity_object_id" {
  description = "core web app Managed Identity object id (used to create its DB role)."
  value       = azurerm_linux_web_app.core.identity[0].principal_id
}

output "app_identity_object_id" {
  description = "app web app Managed Identity object id (used to create its DB role)."
  value       = azurerm_linux_web_app.app.identity[0].principal_id
}

output "grant_db_access_hint" {
  description = "Run infra/grant-db-access.sql against the DB (as the Entra admin) with these role names."
  value       = "core role: ${local.core_name} (read/write) · app role: ${local.app_name} (read-only)"
}

output "seeder_name" {
  description = "skills-consumer Function App name (empty when enable_seeder is false). Use with `az functionapp restart`."
  value       = var.enable_seeder ? azurerm_linux_function_app.seeder[0].name : ""
}

output "seeder_image" {
  description = "Build & push this image, then restart the seeder function app."
  value       = "${azurerm_container_registry.this.login_server}/seeder:${var.image_tag}"
}

output "aoai_endpoint" {
  description = "Azure OpenAI (AI Foundry) endpoint the seeder calls (empty when enable_seeder is false)."
  value       = local.aoai_endpoint
}

output "language_endpoint" {
  description = "Azure AI Language endpoint wired into core for PII redaction (empty unless redaction_provider = \"azure\"). Reuses the shared account in non-default environments."
  value       = var.enable_redaction ? (local.is_default_env ? azurerm_cognitive_account.language[0].endpoint : data.azurerm_cognitive_account.shared_language[0].endpoint) : ""
}
