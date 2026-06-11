provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
}

# The identity Terraform is running as - used as the PostgreSQL Entra
# administrator so it can create database roles for the web app identities.
data "azurerm_client_config" "current" {}
