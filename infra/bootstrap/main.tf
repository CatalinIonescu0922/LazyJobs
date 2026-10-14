terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.44"
    }
  }
  backend "gcs" {
    bucket = "cv-applier-tfstate-cv-applier-ionescu-catalin"
    prefix = "bootstrap"
  }
}

provider "google" {
  project               = var.project_id
  region                = "europe-west3"
  billing_project       = var.project_id
  user_project_override = true
}

locals {
  required_apis = [
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "billingbudgets.googleapis.com",
    "monitoring.googleapis.com",
    "storage.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "state_bucket" {
  name                        = "cv-applier-tfstate-${var.project_id}"
  location                    = "europe-west3"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }
  depends_on = [google_project_service.apis]
}

resource "google_monitoring_notification_channel" "email_alert" {
  display_name = "Budget email alert"
  type         = "email"

  labels = {
    email_address = "cata.ionescu2003@gmail.com"
  }
  depends_on = [google_project_service.apis]
}

resource "google_billing_budget" "budget" {
  billing_account = var.billing_account_id
  display_name    = "cv-applier"

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "50"
    }
  }

  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.7 }
  threshold_rules { threshold_percent = 0.9 }

  all_updates_rule {
    monitoring_notification_channels = [
      google_monitoring_notification_channel.email_alert.name
    ]
  }
  depends_on = [google_project_service.apis]
}
