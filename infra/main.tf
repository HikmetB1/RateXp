# RateXp on Azure: two Linux web apps (containers) sharing one App Service Plan,
# plus an Azure PostgreSQL Flexible Server.
#
#   core (public)  ──writes──►  PostgreSQL  ◄──reads──  app (dashboard)
#
# Auth to PostgreSQL is passwordless: each web app has a System-Assigned Managed
# Identity and connects with a Microsoft Entra ID access token (see core/db.py).
# Password authentication is disabled on the server entirely.
#
# Images are pulled from an ACR provisioned here using the web apps' identities.

locals {
  suffix    = random_string.suffix.result
  acr_name  = "${replace(var.project, "-", "")}acr${local.suffix}"
  core_name = "${var.project}-core-${local.suffix}"
  app_name  = "${var.project}-app-${local.suffix}"

  core_url = "https://${local.core_name}.azurewebsites.net"
  app_url  = "https://${local.app_name}.azurewebsites.net"

  pg_fqdn         = azurerm_postgresql_flexible_server.this.fqdn
  admin_object_id = var.entra_admin_object_id != "" ? var.entra_admin_object_id : data.azurerm_client_config.current.object_id

  # Passwordless DSNs: the username is the web app's Managed Identity name; the
  # password is supplied at runtime as an Entra token. TLS is required.
  core_dsn = "postgresql://${local.core_name}@${local.pg_fqdn}:5432/${var.pg_database}?sslmode=require"
  app_dsn  = "postgresql://${local.app_name}@${local.pg_fqdn}:5432/${var.pg_database}?sslmode=require"
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${var.project}"
  location = var.location
}

resource "azurerm_container_registry" "this" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = false # web apps pull via their Managed Identities instead
}

# --- PostgreSQL (Entra-only authentication) ---
resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "pg-${var.project}-${local.suffix}"
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  version                       = var.pg_version
  sku_name                      = var.pg_sku_name
  storage_mb                    = var.pg_storage_mb
  public_network_access_enabled = true
  zone                          = "1"

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false # no DB usernames/passwords anywhere
    tenant_id                     = data.azurerm_client_config.current.tenant_id
  }
}

# The deployer becomes the server's Entra admin so it can create the per-app
# database roles (see infra/README.md, post-apply step).
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "admin" {
  server_name         = azurerm_postgresql_flexible_server.this.name
  resource_group_name = azurerm_resource_group.this.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  object_id           = local.admin_object_id
  principal_name      = var.entra_admin_principal_name
  principal_type      = var.entra_admin_principal_type
}

resource "azurerm_postgresql_flexible_server_database" "ratexp" {
  name      = var.pg_database
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

# "Allow Azure services": lets the web apps' dynamic outbound IPs reach the
# server without pinning each one.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# --- Compute ---
resource "azurerm_service_plan" "this" {
  name                = "plan-${var.project}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  os_type             = "Linux"
  sku_name            = var.plan_sku
}

# --- core: public ingestion service ---
resource "azurerm_linux_web_app" "core" {
  name                = local.core_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_service_plan.this.location
  service_plan_id     = azurerm_service_plan.this.id

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      docker_image_name   = "core:${var.image_tag}"
      docker_registry_url = "https://${azurerm_container_registry.this.login_server}"
    }
    container_registry_use_managed_identity = true
  }

  app_settings = {
    WEBSITES_PORT     = "8000"
    RATEXP_DB_AUTH    = "entra"
    DATABASE_URL      = local.core_dsn
    RATEXP_SUBMIT_URL = "${local.core_url}/feedback"
  }
}

# --- app: dashboard (read-only API + UI), the only place app-be is reachable ---
resource "azurerm_linux_web_app" "app" {
  name                = local.app_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_service_plan.this.location
  service_plan_id     = azurerm_service_plan.this.id

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      docker_image_name   = "app:${var.image_tag}"
      docker_registry_url = "https://${azurerm_container_registry.this.login_server}"
    }
    container_registry_use_managed_identity = true
  }

  app_settings = {
    WEBSITES_PORT       = "8000"
    RATEXP_DB_AUTH      = "entra"
    DATABASE_URL        = local.app_dsn
    RATEXP_ENV          = "prod"
    RATEXP_CORS_ORIGINS = local.app_url # same-origin; the UI is served by app itself
  }
}

# Let each web app's identity pull images from the ACR.
resource "azurerm_role_assignment" "acr_pull" {
  for_each = {
    core = azurerm_linux_web_app.core.identity[0].principal_id
    app  = azurerm_linux_web_app.app.identity[0].principal_id
  }

  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = each.value
}
