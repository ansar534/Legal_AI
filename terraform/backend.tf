# Remote state in the same storage account that already holds uploads,
# in a container dedicated to Terraform state. The container is created once
# by hand (terraform/bootstrap.sh) before `terraform init`, since state
# storage can't be provisioned by the Terraform run that needs it.
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-legalai"
    storage_account_name = "stlegalaiuploads"
    container_name       = "tfstate"
    key                  = "legalai.tfstate"
    use_azuread_auth     = true
  }
}
