# The read-only API (which also serves the web app) on Fargate, behind an ALB that only
# CloudFront can reach, and only with the secret origin header.

resource "random_password" "origin_secret" {
  length  = 40
  special = false
}

resource "aws_lb" "api" {
  name                       = var.project
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  idle_timeout               = 60
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/api/health" # 503 until the first ETL run builds the index
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  deregistration_delay = 15
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  # Anything not coming through CloudFront (no secret header) is refused.
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_secret.result]
    }
  }
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.atlas.repository_url}:latest"
    essential    = true
    command      = ["atlas", "serve", "--host", "0.0.0.0", "--port", "8000", "--behind-proxy"]
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "ATLAS_API_STATEMENT_TIMEOUT_MS", value = "10000" },
    ]
    secrets = [
      { name = "ATLAS_READ_ONLY_DATABASE_URL", valueFrom = aws_secretsmanager_secret.read_only_database_url.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${var.project}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true # outbound to ECR/Secrets Manager without a NAT gateway
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # CI deploys new images by registering task definition revisions; don't fight it.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener_rule.from_cloudfront]
}
