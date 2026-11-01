variable "subscription_id" {
  description = "Azure subscription that holds rg-legalai."
  type        = string
  default     = "c86eacda-4e54-4a36-ad26-e23e4cbbf3bf"
}

variable "tenant_id" {
  description = "Azure AD tenant (University of Houston)."
  type        = string
  default     = "170bbabd-a2f0-4c90-ad4b-0e8f0f0c4259"
}

variable "location" {
  description = "Primary region for new resources."
  type        = string
  default     = "northcentralus"
}

variable "alert_emails" {
  description = "Addresses the 5xx alert action group notifies."
  type        = list(string)
  default = [
    "amoha210@cougarnet.uh.edu",
    "ypadhye@cougarnet.uh.edu",
  ]
}

variable "postgres_admin_password" {
  description = <<-EOT
    Admin password for pg-legalai-m4. Azure never returns this value on
    read, and the resource's lifecycle.ignore_changes covers it, so this
    placeholder is never sent to Azure for an already-imported server —
    it only matters if the server were ever recreated from scratch.
  EOT
  type      = string
  sensitive = true
  default   = "not-used-after-import-see-ignore_changes"
}

variable "github_repository" {
  description = "GitHub repo the deploy workflow's OIDC federated credential trusts, as org/repo."
  type        = string
  default     = "ansar534/Legal_AI"
}
