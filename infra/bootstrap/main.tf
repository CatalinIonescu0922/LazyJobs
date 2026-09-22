terraform {
  required_version = "~>7.44"
  required_providers {
    google = {
        source = "hashicorp/google"
        version = "~>5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region = "europe-west3"
  billing_project = var.project_id
  user_project_override = true
}

locals {
  required_api_permissions = [
    "cloudresourcemanager.googleapis.com" , 
    "serviceusage.googleapis.com" , 
    "billingbudgets.googleapis.com" ,
    "storage.googleapis.com"
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(required_api_permissions)
  project = var.project_id
  service = each.value
  disable_on_destroy = false
}