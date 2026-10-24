# ECS cluster: the API on Fargate, ETL tasks on one EC2 instance whose disk keeps the 12 GB
# OSM extract and the DuckDB file between runs.

resource "aws_ecs_cluster" "main" {
  name = var.project
  setting {
    name  = "containerInsights"
    value = "disabled" # enable for per-task metrics (extra CloudWatch cost)
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/${var.project}/api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "etl" {
  name              = "/${var.project}/etl"
  retention_in_days = 30
}

# --- IAM ----------------------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by ECS itself to pull images, write logs, and read the secrets into env vars.
resource "aws_iam_role" "task_execution" {
  name               = "${var.project}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  name = "read-secrets"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.database_url.arn,
        aws_secretsmanager_secret.read_only_database_url.arn,
        aws_secretsmanager_secret.reader_password.arn,
        aws_secretsmanager_secret.firms_key.arn,
      ]
    }]
  })
}

# The application itself calls no AWS APIs, so its task role has no permissions.
resource "aws_iam_role" "task" {
  name               = "${var.project}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# --- ETL instance -------------------------------------------------------------------------------

data "aws_ssm_parameter" "ecs_ami_arm64" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/arm64/recommended/image_id"
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "etl_instance" {
  name               = "${var.project}-etl-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "etl_instance_ecs" {
  role       = aws_iam_role.etl_instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

# Lets you open a shell on the instance through Session Manager (no SSH keys or open ports).
resource "aws_iam_role_policy_attachment" "etl_instance_ssm" {
  role       = aws_iam_role.etl_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "etl" {
  name = "${var.project}-etl"
  role = aws_iam_role.etl_instance.name
}

resource "aws_launch_template" "etl" {
  name_prefix   = "${var.project}-etl-"
  image_id      = data.aws_ssm_parameter.ecs_ami_arm64.value
  instance_type = var.etl_instance_type

  iam_instance_profile {
    arn = aws_iam_instance_profile.etl.arn
  }
  vpc_security_group_ids = [aws_security_group.etl.id]

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.etl_disk_gb
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true # the extract can always be re-downloaded
    }
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  user_data = base64encode(<<-EOT
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.main.name}" >> /etc/ecs/ecs.config
    mkdir -p /var/lib/atlas-data
    # Swap gives the weekly OSM update room beyond RAM on small instances.
    if [ ${var.etl_swap_gb} -gt 0 ] && [ ! -f /swapfile ]; then
      fallocate -l ${var.etl_swap_gb}G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
      echo "/swapfile none swap sw 0 0" >> /etc/fstab
    fi
  EOT
  )
}

resource "aws_autoscaling_group" "etl" {
  name                  = "${var.project}-etl"
  min_size              = 1
  max_size              = 1
  desired_capacity      = 1
  vpc_zone_identifier   = [aws_subnet.public[0].id] # one AZ: the data disk lives with the instance
  protect_from_scale_in = true

  launch_template {
    id      = aws_launch_template.etl.id
    version = "$Latest"
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }
  tag {
    key                 = "Name"
    value               = "${var.project}-etl"
    propagate_at_launch = true
  }
}

resource "aws_ecs_capacity_provider" "etl" {
  name = "${var.project}-etl"
  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.etl.arn
    managed_termination_protection = "ENABLED"
    managed_scaling {
      status = "DISABLED" # fixed single instance
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", aws_ecs_capacity_provider.etl.name]
}
