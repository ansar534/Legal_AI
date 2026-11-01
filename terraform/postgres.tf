# Private-only Flexible Server. Azure never returns the admin password on
# read, so it's a write-only field as far as plan/apply is concerned: set
# once (var.postgres_admin_password, sourced from Key Vault, never written to
# a .tfvars file) and ignored afterward via lifecycle.ignore_changes below,
# so no later `terraform plan` ever needs the real value again.
resource "azurerm_postgresql_flexible_server" "main" {
  name                = "pg-legalai-m4"
  resource_group_name = azurerm_resource_group.main.name
  location            = "North Central US"

  version      = "16"
  sku_name     = "B_Standard_B1ms"
  storage_mb   = 32768
  storage_tier = "P4"

  administrator_login    = "legalaiadmin"
  administrator_password = var.postgres_admin_password

  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  auto_grow_enabled = false

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]

  lifecycle {
    # The cluster is deliberately stopped between class sessions to save
    # Azure-for-Students credit; that is an operational toggle, not drift.
    # administrator_password: write-only, see comment above.
    ignore_changes = [tags, administrator_password]
  }
}
