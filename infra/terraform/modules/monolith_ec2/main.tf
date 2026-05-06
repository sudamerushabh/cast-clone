locals {
  base_tags = merge(var.tags, { Module = "cast-clone-monolith-ec2" })

  bedrock_region = coalesce(var.bedrock_region, data.aws_region.current.name)

  user_data = templatefile("${path.module}/templates/user-data.sh.tftpl", {
    region                       = data.aws_region.current.name
    bedrock_region               = local.bedrock_region
    pg_password_secret_arn       = var.pg_password_secret_arn
    neo4j_password_secret_arn    = var.neo4j_password_secret_arn
    license_jwt_secret_arn       = var.license_jwt_secret_arn
    anthropic_api_key_secret_arn = var.anthropic_api_key_secret_arn == null ? "" : var.anthropic_api_key_secret_arn
    openai_api_key_secret_arn    = var.openai_api_key_secret_arn == null ? "" : var.openai_api_key_secret_arn
    ai_provider                  = var.ai_provider
    image_registry               = var.image_registry

    docker_compose = templatefile("${path.module}/templates/docker-compose.yml.tftpl", {
      image_registry      = var.image_registry
      image_tag           = var.image_tag
      backend_image_name  = var.backend_image_name
      frontend_image_name = var.frontend_image_name
      mcp_image_name      = var.mcp_image_name
      ai_provider         = var.ai_provider
      bedrock_region      = local.bedrock_region
    })

    caddyfile = file("${path.module}/templates/Caddyfile")
  })
}

data "aws_region" "current" {}

data "aws_ami" "al2023" {
  count       = var.ami_id == null ? 1 : 0
  most_recent = true
  owners      = ["137112412989"] # Amazon

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-monolith"
  description = "Cast-Clone T1 monolith - 443 inbound, optional 22"
  vpc_id      = var.vpc_id
  tags        = merge(local.base_tags, { Name = "${var.name_prefix}-monolith" })
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  count             = length(var.allow_https_from_cidrs)
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = var.allow_https_from_cidrs[count.index]
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "HTTPS"
}

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  count             = length(var.allow_ssh_from_cidrs)
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = var.allow_ssh_from_cidrs[count.index]
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  description       = "SSH"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "All egress"
}

resource "aws_instance" "this" {
  ami                    = var.ami_id != null ? var.ami_id : data.aws_ami.al2023[0].id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.this.id]
  iam_instance_profile   = var.iam_instance_profile_name
  key_name               = var.key_name
  user_data              = local.user_data

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_size           = var.root_volume_size_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
    tags                  = merge(local.base_tags, { Name = "${var.name_prefix}-root" })
  }

  tags = merge(local.base_tags, {
    Name            = "${var.name_prefix}-monolith"
    CastCloneBackup = "true"
  })

  # User-data is applied once per instance lifetime. Updates require a manual re-run via SSM.
  lifecycle {
    ignore_changes = [user_data]
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = aws_instance.this.availability_zone
  size              = var.data_volume_size_gb
  type              = "gp3"
  iops              = var.data_volume_iops
  throughput        = var.data_volume_throughput
  encrypted         = true

  tags = merge(local.base_tags, {
    Name            = "${var.name_prefix}-data"
    CastCloneBackup = "true"
  })
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.this.id
}

resource "aws_eip" "this" {
  count    = var.allocate_eip ? 1 : 0
  instance = aws_instance.this.id
  domain   = "vpc"
  tags     = merge(local.base_tags, { Name = "${var.name_prefix}-eip" })
}
