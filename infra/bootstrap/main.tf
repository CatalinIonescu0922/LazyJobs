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

resource "google_storage_bucket" "state_bucket" {
  name = "cv-applier-tfstate-${var.project_id}" 
  location = "europe-west3"
  uniform_bucket_level_access = true
  force_destroy = false

  versioning {
    enabled = true
  }
  depends_on = [ google_project_service.storage_api ]
}

resource "google_billing_budget" "buget" {
  billing_account = var.billing_account_id
  display_name = "cv-applier"
  amount {
    specified_amount {
      currency_code = "USD"
      units = 50
    } 
  }
  threshold_rules {
    threshold_percent = 0.5

  }
  threshold_rules {
    threshold_percent = 0.7
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  all_updates_rule {
    monitoring_notification_channels = [
      google_monitoring_notification_channel.email_alert.name
    ]
  }
  depends_on = [ google_project_service.apis ]
}

resource "google_monitoring_notification_channel" "email_alert" {
  display_name = "Buget email alert"
  type = email

  labels = {
    email_address = "cata.ionescu2003@gmail.com"
  }
}