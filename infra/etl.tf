# The ETL runs as one-off ECS tasks on the ETL instance, never as an always-on process.
#
#   Manual (default): "Run ETL" GitHub workflow, or scripts/run-etl.sh sync|facilities
#   Automatic:        set sync_schedule / facilities_schedule and `terraform apply`
#
# Both paths start the exact same task with the same commands.

locals {
  etl_commands = {
    sync       = ["atlas", "sync"]
    facilities = ["sh", "-c", "atlas facilities --force && atlas index"]
  }
}

resource "aws_ecs_task_definition" "etl" {
  family                   = "${var.project}-etl"
  requires_compatibilities = ["EC2"]
  # Host networking: the task uses the instance's public IP for outbound access (no NAT needed).
  network_mode       = "host"
  execution_role_arn = aws_iam_role.task_execution.arn
  task_role_arn      = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  volume {
    name      = "atlas-data"
    host_path = "/var/lib/atlas-data" # survives between runs: OSM extract, DuckDB, landing files
  }

  container_definitions = jsonencode([{
    name              = "etl"
    image             = "${aws_ecr_repository.atlas.repository_url}:latest"
    essential         = true
    command           = local.etl_commands.sync
    memoryReservation = var.etl_memory_mb # soft limit: the task can use more (and swap) if it's free
    mountPoints       = [{ sourceVolume = "atlas-data", containerPath = "/data" }]
    environment = [
      { name = "ATLAS_DATA_DIR", value = "/data" },
      { name = "ATLAS_READER_ROLE", value = "atlas_api" },
      { name = "ATLAS_OSM_REGIONS", value = var.osm_regions },
      { name = "ATLAS_OSM_UPDATE_MAX_MB", value = tostring(var.osm_update_max_mb) },
    ]
    secrets = [
      { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
      { name = "ATLAS_READER_PASSWORD", valueFrom = aws_secretsmanager_secret.reader_password.arn },
      { name = "NASA_FIRMS_API_KEY", valueFrom = aws_secretsmanager_secret.firms_key.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.etl.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "etl"
      }
    }
  }])
}

# --- Optional schedules (off unless the variables are set) --------------------------------------

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  count              = (var.sync_schedule != null || var.facilities_schedule != null) ? 1 : 0
  name               = "${var.project}-etl-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  count = length(aws_iam_role.scheduler)
  name  = "run-etl"
  role  = aws_iam_role.scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = ["ecs:RunTask"]
        Resource  = ["${aws_ecs_task_definition.etl.arn_without_revision}:*"]
        Condition = { ArnLike = { "ecs:cluster" = aws_ecs_cluster.main.arn } }
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.task_execution.arn, aws_iam_role.task.arn]
      },
    ]
  })
}

resource "aws_scheduler_schedule" "etl" {
  for_each = {
    for name, expression in { sync = var.sync_schedule, facilities = var.facilities_schedule } :
    name => expression if expression != null
  }

  name                = "${var.project}-etl-${each.key}"
  schedule_expression = each.value

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler[0].arn

    ecs_parameters {
      # Without a revision: always runs the newest image CI has deployed.
      task_definition_arn = aws_ecs_task_definition.etl.arn_without_revision
      capacity_provider_strategy {
        capacity_provider = aws_ecs_capacity_provider.etl.name
        weight            = 1
      }
    }

    input = jsonencode({
      containerOverrides = [{ name = "etl", command = local.etl_commands[each.key] }]
    })

    retry_policy {
      maximum_retry_attempts = 0 # the next scheduled run is the retry
    }
  }
}
