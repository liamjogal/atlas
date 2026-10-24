variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "atlas"
}

variable "region" {
  description = "AWS region. us-east-1 is cheapest and is required for CloudFront's WAF."
  type        = string
  default     = "us-east-1"
}

variable "github_repository" {
  description = "owner/name of the GitHub repo allowed to deploy and run the ETL (via OIDC)."
  type        = string
  default     = "liamjogal/atlas"
}

variable "alarm_email" {
  description = "Where alarms are emailed (confirm the subscription email AWS sends). Empty = no email."
  type        = string
  default     = ""
}

# --- ETL scheduling: manual by default ----------------------------------------------------------
# Leave null to run the ETL only by hand ("Run ETL" GitHub workflow or scripts/run-etl.sh).
# Set to an EventBridge Scheduler expression to run it automatically, e.g. "rate(5 minutes)".

variable "sync_schedule" {
  description = "Schedule for `atlas sync` (live feeds + re-index), or null for manual only."
  type        = string
  default     = null
}

variable "facilities_schedule" {
  description = "Schedule for the Geofabrik facility refresh + re-index, e.g. \"rate(7 days)\", or null for manual only."
  type        = string
  default     = null
}

# --- Sizing -------------------------------------------------------------------------------------

variable "api_count" {
  description = "Number of API tasks behind the load balancer."
  type        = number
  default     = 2
}

variable "api_cpu" {
  type    = number
  default = 256
}

variable "api_memory" {
  type    = number
  default = 512
}

variable "etl_instance_type" {
  description = "EC2 instance for ETL tasks (needs ~4 GB RAM for the weekly OSM steps; Graviton)."
  type        = string
  default     = "t4g.medium"
}

variable "etl_disk_gb" {
  description = "Disk for the 12 GB OSM extract, its rewrite during updates, and DuckDB."
  type        = number
  default     = 40
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "waf_enabled" {
  description = "Attach a WAF (rate limiting + AWS common rules) to CloudFront. ~$7/month."
  type        = bool
  default     = true
}

variable "waf_rate_limit" {
  description = "Max requests per IP per 5 minutes before WAF blocks. A page load makes ~15 API calls."
  type        = number
  default     = 1000
}

variable "osm_regions" {
  description = "Geofabrik extracts for facilities (comma-separated)."
  type        = string
  default     = "north-america/us,north-america/us/puerto-rico"
}
