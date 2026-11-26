output "api_url" {
  value = module.docagent.api_url
}

output "state_machine_arn" {
  value = module.docagent.state_machine_arn
}

output "uploads_bucket_name" {
  value = module.docagent.uploads_bucket_name
}

output "intake_queue_url" {
  value = module.docagent.intake_queue_url
}

output "table_names" {
  value = module.docagent.table_names
}
