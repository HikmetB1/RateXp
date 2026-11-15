# RateXp on Azure: two Linux web apps and the retention Function (containers) sharing one
# App Service Plan, plus an Azure PostgreSQL Flexible Server.
#
#   core (public)  ──writes──►  PostgreSQL  ◄──reads──  app (dashboard)
#                                   ▲
#                       retention ──┘ deletes old ratings, hourly
#
# Auth to PostgreSQL is passwordless: each web app and the retention Function has a
# System-Assigned Managed Identity and connects with a Microsoft Entra ID access token (see
# core/modules/write/connect_to_postgres.py).
# Password authentication is disabled on the server entirely.
#
# Images are pulled from an ACR provisioned here using the web apps' and Functions' identities.

locals {
  # Deterministic, suffix-free resource names. The default (prod) env is just the
  # project name (so the dashboard is ratexp-app.azurewebsites.net); a named env
  # (e.g. "dev") prefixes it (ratexp-dev-app). Names that must be globally unique
  # (web apps, ACR, storage, PostgreSQL, cognitive subdomains) therefore have to be
  # free across all of Azure for the chosen project/environment.
  is_default_env = var.environment == ""
  name_base      = local.is_default_env ? var.project : "${var.project}-${var.environment}"
  # The environment that core marks its Dynatrace and Bluebox records with.
  environment_name = local.is_default_env ? "prod" : var.environment

  acr_name    = "${replace(local.name_base, "-", "")}acr"
  core_name   = "${local.name_base}-core"
  app_name    = "${local.name_base}-app"
  seeder_name = "${local.name_base}-seeder"
  # The hourly delete of what core/config.yaml retention no longer keeps.
  retention_name = "${local.name_base}-retention"

  # Storage account names: lowercase alphanumeric only, <=24 chars, globally unique.
  seeder_sa_name    = "${replace(local.name_base, "-", "")}seed"
  retention_sa_name = "${replace(local.name_base, "-", "")}retain"

  # Azure OpenAI (AI Foundry) account the seeder's agent and core's labeling call - one per
  # environment, provisioned when either is on.
  aoai_name     = "${local.name_base}-aoai"
  enable_aoai   = var.enable_seeder || var.enable_labeling
  aoai_endpoint = local.enable_aoai ? azurerm_cognitive_account.aoai[0].endpoint : ""

  core_url = "https://${local.core_name}.azurewebsites.net"
  app_url  = "https://${local.app_name}.azurewebsites.net"

  # A non-default environment can put its database on an existing server
  # (shared_postgres_server_name) in place of a server of its own.
  shared_pg       = var.shared_postgres_server_name != ""
  pg_server_id    = local.shared_pg ? data.azurerm_postgresql_flexible_server.shared[0].id : azurerm_postgresql_flexible_server.this[0].id
  pg_fqdn         = local.shared_pg ? data.azurerm_postgresql_flexible_server.shared[0].fqdn : azurerm_postgresql_flexible_server.this[0].fqdn
  admin_object_id = var.entra_admin_object_id != "" ? var.entra_admin_object_id : data.azurerm_client_config.current.object_id

  # Passwordless DSNs: the username is the web app's Managed Identity name; the
  # password is supplied at runtime as an Entra token. TLS is required.
  core_dsn = "postgresql://${local.core_name}@${local.pg_fqdn}:5432/${var.pg_database}?sslmode=require"
  app_dsn  = "postgresql://${local.app_name}@${local.pg_fqdn}:5432/${var.pg_database}?sslmode=require"
  # The retention Function's role may only read and delete (see grant-db-access.sql).
  retention_dsn = "postgresql://${local.retention_name}@${local.pg_fqdn}:5432/${var.pg_database}?sslmode=require"

  # The Language account is always provisioned when enable_redaction (whichever provider
  # core actively uses), so flipping to the azure adapter needs no re-provisioning. Null
  # only when redaction is off.
  language_id = var.enable_redaction ? (local.is_default_env ? azurerm_cognitive_account.language[0].id : data.azurerm_cognitive_account.shared_language[0].id) : null
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.name_base}"
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
  count                         = local.shared_pg ? 0 : 1
  name                          = "pg-${local.name_base}"
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
# database roles (see docs/custom-deploy.md, Deploy to Azure, step 3).
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "admin" {
  count               = local.shared_pg ? 0 : 1
  server_name         = azurerm_postgresql_flexible_server.this[0].name
  resource_group_name = azurerm_resource_group.this.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  object_id           = local.admin_object_id
  principal_name      = var.entra_admin_principal_name
  principal_type      = var.entra_admin_principal_type
}

resource "azurerm_postgresql_flexible_server_database" "ratexp" {
  name      = var.pg_database
  server_id = local.pg_server_id
  collation = "en_US.utf8"
  charset   = "utf8"
}

# "Allow Azure services": lets the web apps' dynamic outbound IPs reach the
# server without pinning each one.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure" {
  count            = local.shared_pg ? 0 : 1
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.this[0].id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# The existing server of shared_postgres_server_name already has its Entra admin and the
# "Allow Azure services" rule, so this environment adds only its database to it.
data "azurerm_postgresql_flexible_server" "shared" {
  count               = local.shared_pg ? 1 : 0
  name                = var.shared_postgres_server_name
  resource_group_name = var.shared_postgres_resource_group
}

# A state from before shared_postgres_server_name holds these three without the [0] index.
# These blocks move them to [0], so terraform apply keeps the server and its data in place of
# a new server.
moved {
  from = azurerm_postgresql_flexible_server.this
  to   = azurerm_postgresql_flexible_server.this[0]
}

moved {
  from = azurerm_postgresql_flexible_server_active_directory_administrator.admin
  to   = azurerm_postgresql_flexible_server_active_directory_administrator.admin[0]
}

moved {
  from = azurerm_postgresql_flexible_server_firewall_rule.azure
  to   = azurerm_postgresql_flexible_server_firewall_rule.azure[0]
}

# --- Compute ---
resource "azurerm_service_plan" "this" {
  name                = "plan-${local.name_base}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  os_type             = "Linux"
  sku_name            = var.plan_sku
}

# --- Azure AI Language: transcript PII redaction (optional) ---
# Created only when var.enable_redaction is true. core masks PII via this resource
# before writing to PostgreSQL (see core/modules/redaction/redact_trajectory.py). Passwordless: core's identity
# gets "Cognitive Services User" below. A custom subdomain is required for Entra auth.
resource "azurerm_cognitive_account" "language" {
  count                 = var.enable_redaction && local.is_default_env ? 1 : 0
  name                  = "${local.name_base}-lang"
  resource_group_name   = azurerm_resource_group.this.name
  location              = azurerm_resource_group.this.location
  kind                  = "TextAnalytics"
  sku_name              = var.language_sku_name
  custom_subdomain_name = "${local.name_base}-lang"
  local_auth_enabled    = false # Entra ID only - no access keys
}

# Non-default environments reuse an existing (prod) Language account rather than
# provisioning their own - the free F0 tier is one-per-subscription.
data "azurerm_cognitive_account" "shared_language" {
  count               = var.enable_redaction && !local.is_default_env ? 1 : 0
  name                = var.shared_language_account_name
  resource_group_name = var.shared_language_resource_group
}

# core's identity may call the Language data plane (PII detection) via Entra ID -
# scoped to whichever account this environment uses (its own, or the shared one).
resource "azurerm_role_assignment" "core_language" {
  count                = var.enable_redaction ? 1 : 0
  scope                = local.language_id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_linux_web_app.core.identity[0].principal_id
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
    always_on = true # keep the container warm so the first request after idle has no cold-start delay
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
    RATEXP_PUBLIC_URL = local.core_url
    # Active redaction adapter; flip to "azure" (the Language account is always
    # provisioned) and restart core - no rebuild needed (both adapters ship in the image).
    RATEXP_REDACTION_PROVIDER = var.redaction_provider
    # Tenant URL + token for the app_be_dynatrace destination adapter (see
    # core/modules/write/adapters/); the adapter's enabled flag lives in core/config.yaml. Supply
    # the token via TF_VAR_dynatrace_access_token.
    DT_TENANT_URL   = var.dynatrace_tenant_url
    DT_ACCESS_TOKEN = var.dynatrace_access_token
    # Same for the phoenix destination adapter; supply the key via TF_VAR_phoenix_api_key.
    PHOENIX_COLLECTOR_ENDPOINT = var.phoenix_collector_endpoint
    PHOENIX_API_KEY            = var.phoenix_api_key
    PHOENIX_PROJECT_NAME       = var.phoenix_project_name
    # Same for the bluebox destination adapter; supply the token via TF_VAR_bluebox_otlp_token.
    BLUEBOX_OTLP_ENDPOINT = var.bluebox_otlp_endpoint
    BLUEBOX_OTLP_TOKEN    = var.bluebox_otlp_token
    # The account core labels trajectories with; empty leaves labeling off (see
    # core/modules/labeling/label_trajectory.py). No key: core auths with its identity.
    AZURE_OPENAI_ENDPOINT = var.enable_labeling ? local.aoai_endpoint : ""
    # Marks each record core writes to Dynatrace and Bluebox with this deployment, so one
    # tenant holds prod and dev apart (core/modules/write/adapters/write_to_dynatrace.py).
    OTEL_RESOURCE_ATTRIBUTES = "deployment.environment.name=${local.environment_name}"
  }
}

# --- app: dashboard (read-only API + UI), the only place the dashboard API is reachable ---
resource "azurerm_linux_web_app" "app" {
  name                = local.app_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_service_plan.this.location
  service_plan_id     = azurerm_service_plan.this.id

  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on = true # keep the dashboard warm so the table loads fast on open (no ~60s cold start)
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
    RATEXP_CORE_URL     = local.core_url
    # Which source the dashboard reads is app/ratexp/config.yaml read_adapters, baked into the
    # image. These only supply the credentials for it when that source is Dynatrace.
    DT_QUERY_URL    = var.dynatrace_query_url
    DT_ACCESS_TOKEN = var.dynatrace_access_token
  }
}

# --- Azure OpenAI (AI Foundry): the models the seeder and core's labeling call (optional) ---
# Provisioned when var.enable_seeder or var.enable_labeling is true. Passwordless: each
# caller's Managed Identity holds "Cognitive Services OpenAI User" on it - no API key anywhere.
resource "azurerm_cognitive_account" "aoai" {
  count                 = local.enable_aoai ? 1 : 0
  name                  = local.aoai_name
  resource_group_name   = azurerm_resource_group.this.name
  location              = azurerm_resource_group.this.location
  kind                  = "OpenAI"
  sku_name              = var.aoai_sku_name
  custom_subdomain_name = local.aoai_name
  local_auth_enabled    = false # Entra ID only - no access keys
}

# core labels each consented trajectory with this model (see
# core/modules/labeling/label_trajectory.py), which names it in config.yaml labeling.deployment.
resource "azurerm_cognitive_deployment" "labeling_model" {
  count                = var.enable_labeling ? 1 : 0
  name                 = var.labeling_model
  cognitive_account_id = azurerm_cognitive_account.aoai[0].id

  model {
    format  = "OpenAI"
    name    = var.labeling_model
    version = var.labeling_model_version
  }

  sku {
    name     = var.aoai_deployment_sku
    capacity = var.labeling_capacity
  }
}

resource "azurerm_role_assignment" "core_aoai" {
  count                = var.enable_labeling ? 1 : 0
  scope                = azurerm_cognitive_account.aoai[0].id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_linux_web_app.core.identity[0].principal_id
}

# The deployer too, so labeling can be tried from their machine before a deploy.
resource "azurerm_role_assignment" "admin_aoai" {
  count                = var.enable_labeling ? 1 : 0
  scope                = azurerm_cognitive_account.aoai[0].id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = local.admin_object_id
}

# --- seeder: Azure Function that seeds demo feedback into core (optional) ---
# Provisioned only when var.enable_seeder is true. A timer trigger has a LangChain agent
# run a bundled skill and POST feedback to core's public API. The agent's model is a
# deployment on the Azure OpenAI account above (see seeder/function_app.py).
resource "azurerm_cognitive_deployment" "seeder_model" {
  count                = var.enable_seeder ? 1 : 0
  name                 = var.aoai_deployment
  cognitive_account_id = azurerm_cognitive_account.aoai[0].id

  model {
    format  = "OpenAI"
    name    = var.aoai_model
    version = var.aoai_model_version
  }

  sku {
    name     = var.aoai_deployment_sku
    capacity = var.aoai_capacity
  }
}

# Storage account backing the Functions runtime (required - the timer trigger keeps its
# state here).
resource "azurerm_storage_account" "seeder" {
  count                    = var.enable_seeder ? 1 : 0
  name                     = local.seeder_sa_name
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_linux_function_app" "seeder" {
  count               = var.enable_seeder ? 1 : 0
  name                = local.seeder_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_service_plan.this.location
  service_plan_id     = azurerm_service_plan.this.id

  storage_account_name       = azurerm_storage_account.seeder[0].name
  storage_account_access_key = azurerm_storage_account.seeder[0].primary_access_key

  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on = true # keep the timer trigger firing on the dedicated B1 plan
    application_stack {
      docker {
        registry_url = "https://${azurerm_container_registry.this.login_server}"
        image_name   = "seeder"
        image_tag    = var.image_tag
      }
    }
    container_registry_use_managed_identity = true
  }

  app_settings = {
    # Required for a custom-container Function App: without this, Azure mounts an empty
    # Files share over /home/site/wwwroot and the host can't see the image's code (host
    # finds 0 functions). false = run from the image's filesystem.
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "false"
    FUNCTIONS_WORKER_RUNTIME            = "python"
    SEED_SCHEDULE                       = var.seed_schedule
    RATEXP_CORE_URL                     = local.core_url
    MODEL                               = var.seeder_model
    AZURE_OPENAI_ENDPOINT               = azurerm_cognitive_account.aoai[0].endpoint
    OPENAI_API_VERSION                  = var.openai_api_version
    # No AZURE_OPENAI_API_KEY: the seeder auths with the Managed Identity below
    # (see seeder/modules/agent/open_chat_model.py).
  }
}

# The seeder's identity may call the Azure OpenAI data plane (chat completions) via Entra ID.
resource "azurerm_role_assignment" "seeder_aoai" {
  count                = var.enable_seeder ? 1 : 0
  scope                = azurerm_cognitive_account.aoai[0].id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_linux_function_app.seeder[0].identity[0].principal_id
}

# --- retention: the hourly delete of what core/config.yaml retention no longer keeps ---
# core's own code in its own Functions image (core/Dockerfile.retention); core's web app
# never deletes. Its database role may only SELECT and DELETE (see grant-db-access.sql).
resource "azurerm_storage_account" "retention" {
  name                     = local.retention_sa_name
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_linux_function_app" "retention" {
  name                = local.retention_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_service_plan.this.location
  service_plan_id     = azurerm_service_plan.this.id

  storage_account_name       = azurerm_storage_account.retention.name
  storage_account_access_key = azurerm_storage_account.retention.primary_access_key

  identity {
    type = "SystemAssigned"
  }

  site_config {
    always_on = true # keep the hourly timer firing on the dedicated B1 plan
    application_stack {
      docker {
        registry_url = "https://${azurerm_container_registry.this.login_server}"
        image_name   = "retention"
        image_tag    = var.image_tag
      }
    }
    container_registry_use_managed_identity = true
  }

  app_settings = {
    # As on the seeder: without it the host can't see the image's code.
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "false"
    FUNCTIONS_WORKER_RUNTIME            = "python"
    RATEXP_DB_AUTH                      = "entra"
    DATABASE_URL                        = local.retention_dsn
    # Phoenix, the one other destination it deletes from, with the values core writes to it
    # with. The OTLP destinations (Dynatrace, Bluebox) get none: retention skips them.
    PHOENIX_COLLECTOR_ENDPOINT = var.phoenix_collector_endpoint
    PHOENIX_API_KEY            = var.phoenix_api_key
    PHOENIX_PROJECT_NAME       = var.phoenix_project_name
  }
}

# Let each web app's (and each Function's) identity pull images from the ACR.
resource "azurerm_role_assignment" "acr_pull" {
  for_each = merge(
    {
      core      = azurerm_linux_web_app.core.identity[0].principal_id
      app       = azurerm_linux_web_app.app.identity[0].principal_id
      retention = azurerm_linux_function_app.retention.identity[0].principal_id
    },
    var.enable_seeder ? { seeder = azurerm_linux_function_app.seeder[0].identity[0].principal_id } : {},
  )

  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = each.value
}
