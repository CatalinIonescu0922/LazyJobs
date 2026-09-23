output "state_bucket" {
  value = google_storage_bucket.state_bucket.name
  description = "THe bucket where terraform places it s state"
}