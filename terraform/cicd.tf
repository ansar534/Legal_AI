# Keyless GitHub Actions -> Azure login via a user-assigned managed identity
# federated with GitHub's OIDC issuer (trusted only for pushes to main in this
# repo). UH Azure AD blocks creating App Registrations / service principals for
# student accounts, so we use azurerm federated credentials on a managed
# identity instead of azuread_application.
resource "azurerm_user_assigned_identity" "github_deploy" {
  name                = "id-legalai-github"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
}

resource "azurerm_federated_identity_credential" "github_main" {
  name                = "github-main"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.github_deploy.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_repository}:ref:refs/heads/main"
}

# Scoped to exactly what the pipeline does: push images and roll out the
# existing k8s manifests. Nothing broader (no Contributor on the RG).
resource "azurerm_role_assignment" "github_deploy_acr_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.github_deploy.principal_id
}

# Cluster has local accounts (no AAD/Azure RBAC), so the pipeline downloads
# admin kubeconfig. Cluster Admin Role is required for that path.
resource "azurerm_role_assignment" "github_deploy_aks_cluster_admin" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service Cluster Admin Role"
  principal_id         = azurerm_user_assigned_identity.github_deploy.principal_id
}
