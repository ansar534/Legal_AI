# rg-legalai also contains a second VNet, rg-legalai-vnet, left over from the
# Milestone 4 VM. It is unused by AKS or Postgres and is intentionally not
# imported here — see terraform/README.md "Exceptions".
resource "azurerm_resource_group" "main" {
  name     = "rg-legalai"
  location = "centralus"
}

resource "azurerm_virtual_network" "main" {
  name                = "vnet-northcentralus-1"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  address_space       = ["172.16.0.0/16"]
}

resource "azurerm_subnet" "legacy_vm" {
  name                 = "snet-northcentralus-1"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["172.16.0.0/24"]
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["172.16.1.0/24"]

  delegation {
    name = "0"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }

  service_endpoints = ["Microsoft.Storage"]
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["172.16.2.0/24"]
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "legalai-m4.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-vnet-legalai"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.main.id
}
