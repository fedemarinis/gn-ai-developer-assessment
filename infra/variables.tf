# Input variables. Every variable has a default, so `terraform validate`
# (and a future `plan`) needs no extra input. Override with -var or a
# git-ignored *.tfvars file. `terraform validate` cannot check variable
# values, so the validation blocks reject bad input at plan time instead.

variable "project_name" {
  description = "Prefix for all resource names. The web app name must be globally unique in Azure (<name>.azurewebsites.net), so change this placeholder before a real deployment."
  type        = string
  default     = "gn-ticketing"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,40}$", var.project_name))
    error_message = "project_name must be 3-40 characters: lowercase letters, digits and hyphens."
  }
}

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "westeurope"
}

variable "sku_name" {
  description = "App Service plan size. B1 (Basic) is the smallest tier that supports always_on. F1 (Free) would also need always_on = false."
  type        = string
  default     = "B1"

  validation {
    condition     = contains(["B1", "B2", "B3", "S1", "P0v3", "P1v3"], var.sku_name)
    error_message = "sku_name must be one of: B1, B2, B3, S1, P0v3, P1v3."
  }
}

variable "python_version" {
  description = "Python runtime of the web app. Matches the Python version used for development and CI."
  type        = string
  default     = "3.12"
}

variable "tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default = {
    project    = "gn-ticketing-assessment"
    managed_by = "terraform"
  }
}
