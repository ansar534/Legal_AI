# Account keys are disabled (shared_access_key_enabled = false): the app and
# every operator reach this account with an RBAC role assignment instead,
# never a key.
resource "azurerm_storage_account" "uploads" {
  name                            = "stlegalaiuploads"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  access_tier                     = "Hot"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  shared_access_key_enabled       = false
  public_network_access_enabled   = true
  allow_nested_items_to_be_public = false

  lifecycle {
    # terraform/README.md: created once as the Terraform state backend
    # before `terraform init` could run against this account.
    ignore_changes = [tags]
  }
}

resource "azurerm_storage_container" "uploads" {
  name                  = "uploads"
  storage_account_id    = azurerm_storage_account.uploads.id
  container_access_type = "private"
}

# Terraform state for this project. Created by hand (terraform/bootstrap.sh)
# before `terraform init` can point the azurerm backend at it — then imported
# here like every other pre-existing resource, so it stays under management.
resource "azurerm_storage_container" "tfstate" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.uploads.id
  container_access_type = "private"

  lifecycle {
    prevent_destroy = true
  }
}
