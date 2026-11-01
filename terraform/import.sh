#!/usr/bin/env bash
# One-time import of every pre-existing Azure resource into Terraform state.
# Run once, from terraform/, after `terraform init`. Safe to re-run: a
# resource already in state is simply skipped (the `|| true` tolerates
# "Resource already managed by Terraform").
set -uo pipefail

SUB=c86eacda-4e54-4a36-ad26-e23e4cbbf3bf
RG=/subscriptions/$SUB/resourceGroups/rg-legalai

imp() { terraform import "$1" "$2" || true; }

imp azurerm_resource_group.main "$RG"

imp azurerm_virtual_network.main "$RG/providers/Microsoft.Network/virtualNetworks/vnet-northcentralus-1"
imp azurerm_subnet.legacy_vm "$RG/providers/Microsoft.Network/virtualNetworks/vnet-northcentralus-1/subnets/snet-northcentralus-1"
imp azurerm_subnet.postgres "$RG/providers/Microsoft.Network/virtualNetworks/vnet-northcentralus-1/subnets/snet-postgres"
imp azurerm_subnet.aks "$RG/providers/Microsoft.Network/virtualNetworks/vnet-northcentralus-1/subnets/snet-aks"

imp azurerm_private_dns_zone.postgres "$RG/providers/Microsoft.Network/privateDnsZones/legalai-m4.postgres.database.azure.com"
imp azurerm_private_dns_zone_virtual_network_link.postgres "$RG/providers/Microsoft.Network/privateDnsZones/legalai-m4.postgres.database.azure.com/virtualNetworkLinks/link-vnet-legalai"

imp azurerm_user_assigned_identity.app "$RG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-legalai-app"
imp azurerm_federated_identity_credential.app_workload_identity "$RG/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-legalai-app/federatedIdentityCredentials/aks-legal-ai-hub"

imp azurerm_key_vault.main "$RG/providers/Microsoft.KeyVault/vaults/kv-legalai-m4"

imp azurerm_storage_account.uploads "$RG/providers/Microsoft.Storage/storageAccounts/stlegalaiuploads"
imp azurerm_storage_container.uploads "https://stlegalaiuploads.blob.core.windows.net/uploads"
imp azurerm_storage_container.tfstate "https://stlegalaiuploads.blob.core.windows.net/tfstate"

imp azurerm_container_registry.main "$RG/providers/Microsoft.ContainerRegistry/registries/legalai"

imp azurerm_postgresql_flexible_server.main "$RG/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-legalai-m4"

imp azurerm_kubernetes_cluster.main "$RG/providers/Microsoft.ContainerService/managedClusters/aks-legalai"

# Role assignments for id-legalai-app (GUIDs captured from `az role assignment list`).
imp azurerm_role_assignment.app_keyvault_secrets_user "$RG/providers/Microsoft.KeyVault/vaults/kv-legalai-m4/providers/Microsoft.Authorization/roleAssignments/be6f6008-0f19-412a-ab51-fbd8462b7301"
imp azurerm_role_assignment.app_storage_blob_contributor "$RG/providers/Microsoft.Storage/storageAccounts/stlegalaiuploads/blobServices/default/containers/uploads/providers/Microsoft.Authorization/roleAssignments/8e954541-232f-44fc-8810-910d4ef50871"
imp azurerm_role_assignment.app_acr_pull "$RG/providers/Microsoft.ContainerRegistry/registries/legalai/providers/Microsoft.Authorization/roleAssignments/6e57fa20-7d84-4d4c-b136-fd73c09ed99c"

echo "Import pass complete. Run 'terraform plan' next and fix any remaining diffs resource by resource."
