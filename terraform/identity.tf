# id-legalai-app is the workload identity the app pod authenticates as
# (federated with the AKS OIDC issuer, subject system:serviceaccount:legal-ai:legal-ai-hub).
# Its three role assignments below are the ones the app actually needs;
# AKS's own auto-created identities (kubelet -> AcrPull, cluster identity ->
# Network/Resource Contributor) are managed by the AKS resource provider
# itself and are intentionally not imported — see terraform/README.md.
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-legalai-app"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
}

resource "azurerm_federated_identity_credential" "app_workload_identity" {
  name                = "aks-legal-ai-hub"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.app.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject             = "system:serviceaccount:legal-ai:legal-ai-hub"
}

resource "azurerm_role_assignment" "app_keyvault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_role_assignment" "app_storage_blob_contributor" {
  scope                = "${azurerm_storage_account.uploads.id}/blobServices/default/containers/${azurerm_storage_container.uploads.name}"
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_role_assignment" "app_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}
