resource "azurerm_container_registry" "main" {
  name                          = "legalai"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = var.location
  sku                           = "Basic"
  admin_enabled                 = false
  anonymous_pull_enabled        = false
  export_policy_enabled         = true
  public_network_access_enabled = true
}
