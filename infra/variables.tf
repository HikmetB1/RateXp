variable "subscription_id" {
  description = "Azure subscription to deploy into."
  type        = string
}

variable "project" {
  description = "Short name used to prefix every resource."
  type        = string
  default     = "ratexp"
}

variable "environment" {
  description = "Environment suffix. Empty = the default (prod) deployment, which keeps its random-suffixed names. A non-empty value (e.g. \"dev\") yields clean, suffix-free names like ratexp-dev-app."
  type        = string
  default     = ""
}

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "westeurope"
}

variable "plan_sku" {
  description = "App Service Plan SKU shared by both web apps. B1 is the cheapest that runs custom containers."
  type        = string
  default     = "B1"
}

variable "image_tag" {
  description = "Tag of the core/app images in ACR that the web apps run."
  type        = string
  default     = "latest"
}

variable "pg_database" {
  description = "Database name created on the server."
  type        = string
  default     = "ratexp"
}

variable "pg_sku_name" {
  description = "PostgreSQL Flexible Server SKU. Burstable B1ms is the cheapest."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "pg_storage_mb" {
  description = "PostgreSQL storage in MB (smallest tier)."
  type        = number
  default     = 32768
}

variable "pg_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "16"
}

variable "entra_admin_object_id" {
  description = "Entra object id to set as PostgreSQL admin. Defaults to the deployer."
  type        = string
  default     = ""
}

variable "entra_admin_principal_name" {
  description = "Display name of the PostgreSQL Entra admin (user/SP/group name)."
  type        = string
  default     = "ratexp-deployer"
}

variable "entra_admin_principal_type" {
  description = "Type of the Entra admin principal: User, ServicePrincipal, or Group."
  type        = string
  default     = "User"
}

variable "enable_seeder" {
  description = "Provision the skills-consumer Azure Function plus its Azure OpenAI (AI Foundry) account. The timer-triggered agent seeds demo feedback into core and costs model credits. Off by default."
  type        = bool
  default     = false
}

variable "seed_schedule" {
  description = "NCRONTAB cadence (with seconds) for the seeder timer trigger. Default fires every 3s."
  type        = string
  default     = "*/3 * * * * *"
}

variable "seeder_model" {
  description = "LangChain init_chat_model id the seeder uses. azure_openai:<deployment> auths to the AI Foundry account via Managed Identity (passwordless)."
  type        = string
  default     = "azure_openai:gpt-4o-mini"
}

variable "aoai_sku_name" {
  description = "Azure OpenAI account SKU. S0 is the standard pay-as-you-go tier."
  type        = string
  default     = "S0"
}

variable "aoai_deployment" {
  description = "Name of the chat model deployment the seeder targets (must match the deployment in seeder_model)."
  type        = string
  default     = "gpt-4o-mini"
}

variable "aoai_model" {
  description = "Azure OpenAI base model to deploy."
  type        = string
  default     = "gpt-4o-mini"
}

variable "aoai_model_version" {
  description = "Version of the Azure OpenAI base model to deploy."
  type        = string
  default     = "2024-07-18"
}

variable "aoai_deployment_sku" {
  description = "Deployment SKU for the model. gpt-4o-mini in many regions (e.g. westeurope) is only offered as GlobalStandard, not regional Standard."
  type        = string
  default     = "GlobalStandard"
}

variable "aoai_capacity" {
  description = "Deployment capacity in thousands of tokens per minute (TPM). Drawn from the subscription's regional quota."
  type        = number
  default     = 20
}

variable "openai_api_version" {
  description = "Azure OpenAI REST API version the seeder's client uses (OPENAI_API_VERSION app setting)."
  type        = string
  default     = "2024-10-21"
}

variable "enable_redaction" {
  description = "Provision an Azure AI Language account and wire transcript PII redaction into core (see core/redact.py). Off by default."
  type        = bool
  default     = false
}

variable "language_sku_name" {
  description = "Azure AI Language (Cognitive Services) SKU. F0 is the free tier (one per subscription); S is pay-as-you-go."
  type        = string
  default     = "F0"
}

# Non-default environments (e.g. dev) reuse an existing Language account instead of
# creating their own - the free F0 tier is one-per-subscription and already used by
# prod. These point core's redaction at that shared account; leave empty for prod.
variable "shared_language_account_name" {
  description = "Name of an existing Azure AI Language account to reuse for redaction (non-default environments). Empty creates a new account."
  type        = string
  default     = ""
}

variable "shared_language_resource_group" {
  description = "Resource group of the existing Language account named in shared_language_account_name."
  type        = string
  default     = ""
}
