output "github_deploy_client_id" {
  description = "Set as AZURE_CLIENT_ID repo variable for the GitHub Actions OIDC login."
  value       = azurerm_user_assigned_identity.github_deploy.client_id
}

output "tenant_id" {
  value = var.tenant_id
}

output "subscription_id" {
  value = var.subscription_id
}

output "log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.main.id
}
