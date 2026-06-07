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
  description = "Public URL of core — point your skills here (the snippet API)."
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

output "language_endpoint" {
  description = "Azure AI Language endpoint wired into core for PII redaction (empty when enable_redaction is false)."
  value       = var.enable_redaction ? azurerm_cognitive_account.language[0].endpoint : ""
}
