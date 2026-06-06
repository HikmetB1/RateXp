variable "subscription_id" {
  description = "Azure subscription to deploy into."
  type        = string
}

variable "project" {
  description = "Short name used to prefix every resource."
  type        = string
  default     = "ratexp"
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
