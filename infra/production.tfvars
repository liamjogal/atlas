# Production settings, committed so GitHub's Infrastructure workflow and your Mac apply the same
# thing:  terraform plan -var-file=production.tfvars
# No secrets here: generated passwords live in AWS Secrets Manager, the FIRMS key is set with
# put-secret-value. To change production, edit this file in a pull request.

alarm_email = "liamjogal@gmail.com"

# ETL is manual ("Run ETL" in GitHub Actions). To make it automatic, set these and merge:
sync_schedule       = null # e.g. "rate(5 minutes)"
facilities_schedule = null # e.g. "rate(7 days)"

# Lean sizing (the defaults); see terraform.tfvars.example for the larger setup.
