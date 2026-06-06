terraform {
  required_version = ">= 1.5"

  # Local state by default (state files stay on this machine). To use a remote
  # backend, add a `backend "azurerm" { ... }` block and run
  # `terraform init -migrate-state`.

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
