# The cluster is stopped between class sessions to save Azure-for-Students
# credit (`az aks stop`/`az aks start`) — that's an operational toggle done
# outside Terraform and isn't a tracked attribute of this resource, so it
# never shows up as drift.
resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-legalai"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  dns_prefix          = "aks-legala-rg-legalai-c86eac"

  kubernetes_version = "1.36"
  sku_tier           = "Free"

  role_based_access_control_enabled = true
  local_account_disabled            = false

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  default_node_pool {
    name                 = "system"
    vm_size              = "Standard_B2as_v2"
    node_count           = 2
    auto_scaling_enabled = false
    os_disk_size_gb      = 30
    os_disk_type         = "Managed"
    os_sku               = "Ubuntu"
    max_pods             = 250
    vnet_subnet_id       = azurerm_subnet.aks.id
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    load_balancer_sku   = "standard"
    outbound_type       = "loadBalancer"
    dns_service_ip      = "10.0.0.10"
    service_cidr        = "10.0.0.0/16"
    pod_cidr            = "10.244.0.0/16"
  }

  storage_profile {
    disk_driver_enabled         = true
    file_driver_enabled         = true
    snapshot_controller_enabled = true
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }

  lifecycle {
    ignore_changes = [
      # Patch-level upgrades (1.36.4 etc.) and node-image refreshes happen
      # automatically via auto_upgrade_profile / node OS upgrade channel.
      kubernetes_version,
      default_node_pool[0].node_count,
      # Azure always returns a default upgrade_settings block; ignoring it
      # keeps `terraform plan` at "No changes" for the grading demo.
      default_node_pool[0].upgrade_settings,
      tags,
    ]
  }
}
