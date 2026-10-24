# Container registry, Postgres, and the secrets the tasks read at start-up.

resource "aws_ecr_repository" "atlas" {
  name                 = var.project
  image_tag_mutability = "MUTABLE" # `latest` moves; every image is also tagged with its commit SHA
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "atlas" {
  repository = aws_ecr_repository.atlas.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 20 most recent images (enough to roll back)"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}

# --- Postgres -----------------------------------------------------------------------------------

resource "random_password" "db_owner" {
  length  = 32
  special = false # keeps the connection URL free of characters that need escaping
}

resource "random_password" "db_reader" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = var.project
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier              = var.project
  engine                  = "postgres"
  engine_version          = "17"
  instance_class          = var.db_instance_class
  allocated_storage       = 20
  storage_type            = "gp3"
  storage_encrypted       = true
  db_name                 = "atlas"
  username                = "atlas_owner"
  password                = random_password.db_owner.result
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  publicly_accessible     = false
  multi_az                = false
  backup_retention_period = 7
  deletion_protection     = false # set true once this is more than a portfolio project
  skip_final_snapshot     = true
  apply_immediately       = true
}

locals {
  db_host  = aws_db_instance.main.address
  db_owner = "postgresql://atlas_owner:${random_password.db_owner.result}@${local.db_host}:5432/atlas?sslmode=require"
  # The API's role is created and granted by the ETL itself (ATLAS_READER_ROLE/PASSWORD), since
  # Terraform can't reach a database in private subnets.
  db_reader = "postgresql://atlas_api:${random_password.db_reader.result}@${local.db_host}:5432/atlas?sslmode=require"
}

# --- Secrets (injected into tasks as environment variables, never baked into images) ------------

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.project}/database-url"
  description             = "Owner connection for the ETL"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = local.db_owner
}

resource "aws_secretsmanager_secret" "read_only_database_url" {
  name                    = "${var.project}/read-only-database-url"
  description             = "Read-only connection for the API"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "read_only_database_url" {
  secret_id     = aws_secretsmanager_secret.read_only_database_url.id
  secret_string = local.db_reader
}

resource "aws_secretsmanager_secret" "reader_password" {
  name                    = "${var.project}/reader-password"
  description             = "Password the ETL sets on the API's read-only role"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "reader_password" {
  secret_id     = aws_secretsmanager_secret.reader_password.id
  secret_string = random_password.db_reader.result
}

# The FIRMS key is set out of band so it never enters Terraform state:
#   aws secretsmanager put-secret-value --secret-id atlas/nasa-firms-api-key --secret-string '<key>'
resource "aws_secretsmanager_secret" "firms_key" {
  name                    = "${var.project}/nasa-firms-api-key"
  description             = "NASA FIRMS MAP_KEY (set with put-secret-value)"
  recovery_window_in_days = 0
}
