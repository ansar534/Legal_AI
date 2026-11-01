# RBAC-mode vault. Secret *values* (API keys, DB password) are never read
# back into state or committed anywhere — only the vault and who can read
# secrets from it are Terraform-managed.
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  name                       = "kv-legalai-m4"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
}
