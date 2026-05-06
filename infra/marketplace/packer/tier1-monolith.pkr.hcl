packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = "~> 1.3"
    }
  }
}

# ----- Variables -----

variable "version" {
  type        = string
  description = "Cast-Clone release version (e.g. 'v0.1.0'). Used in AMI name + tags."
}

variable "image_registry" {
  type        = string
  description = "ECR registry path holding cast-clone images, e.g. '123456789012.dkr.ecr.us-east-1.amazonaws.com/cast-clone'."
}

variable "image_tag" {
  type        = string
  description = "Tag of cast-clone images to bake into the AMI. Typically equals 'version'."
}

variable "trial_license_jwt" {
  type        = string
  description = "Pre-signed trial JWT (365-day backstop; app enforces actual 14-day window). Generate via infra/scripts/sign-trial-license.sh."
  sensitive   = true
}

variable "build_region" {
  type        = string
  description = "Region the AMI is initially built in. Marketplace replicates from here."
  default     = "us-east-1"
}

variable "ami_regions" {
  type        = list(string)
  description = "Regions to copy the built AMI into. Must match the Marketplace listing's region list."
  default = [
    "us-east-1",
    "us-east-2",
    "us-west-2",
    "eu-west-1",
    "eu-central-1",
    "ap-south-1",
    "ap-south-2",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
  ]
}

variable "ami_name_prefix" {
  type    = string
  default = "cast-clone-t1"
}

# ----- Source AMI -----

source "amazon-ebs" "tier1" {
  region          = var.build_region
  ami_regions     = var.ami_regions
  ami_name        = "${var.ami_name_prefix}-${var.version}-${formatdate("YYYYMMDDhhmmss", timestamp())}"
  ami_description = "Cast-Clone T1 Starter ${var.version}"

  source_ami_filter {
    filters = {
      name                = "al2023-ami-2023.*-kernel-*-x86_64"
      architecture        = "x86_64"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["137112412989"] # Amazon
  }

  instance_type = "m6i.xlarge"
  ssh_username  = "ec2-user"

  # Marketplace requirements: ENA + SR-IOV + IMDSv2.
  ena_support   = true
  sriov_support = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  launch_block_device_mappings {
    device_name           = "/dev/xvda"
    volume_size           = 40
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name      = "${var.ami_name_prefix}-${var.version}"
    Project   = "cast-clone"
    Tier      = "t1-starter"
    Version   = var.version
    BuildDate = formatdate("YYYY-MM-DD", timestamp())
  }

  snapshot_tags = {
    Project = "cast-clone"
    Version = var.version
  }
}

# ----- Build -----

build {
  name    = "cast-clone-tier1"
  sources = ["source.amazon-ebs.tier1"]

  # 1. System dependencies (docker, jq, compose plugin)
  provisioner "shell" {
    script = "${path.root}/scripts/install-deps.sh"
  }

  # 2. Stage app directories
  provisioner "shell" {
    inline = [
      "sudo mkdir -p /opt/cast-clone /etc/cast-clone /var/log/cast-clone",
      "sudo chown -R ec2-user:ec2-user /opt/cast-clone",
    ]
  }

  # 3. Upload runtime files
  provisioner "file" {
    source      = "${path.root}/files/bootstrap.sh"
    destination = "/opt/cast-clone/bootstrap.sh"
  }

  provisioner "file" {
    source      = "${path.root}/files/Caddyfile"
    destination = "/opt/cast-clone/Caddyfile"
  }

  # 4. Render docker-compose.yml with bake-time image refs.
  # Per-customer values (passwords, license, AI provider, region) stay as
  # ${VAR} placeholders for compose to substitute from .env at runtime.
  provisioner "file" {
    content = templatefile("${path.root}/templates/docker-compose.yml.tftpl", {
      image_registry      = var.image_registry
      image_tag           = var.image_tag
      backend_image_name  = "cast-clone-backend"
      frontend_image_name = "cast-clone-frontend"
      mcp_image_name      = "cast-clone-mcp"
    })
    destination = "/opt/cast-clone/docker-compose.yml"
  }

  # 5. Seed the trial license JWT.
  provisioner "shell" {
    environment_vars = ["TRIAL_LICENSE_JWT=${var.trial_license_jwt}"]
    inline = [
      "echo \"$TRIAL_LICENSE_JWT\" | sudo tee /etc/cast-clone/trial-license.jwt > /dev/null",
      "sudo chmod 644 /etc/cast-clone/trial-license.jwt",
    ]
  }

  # 6. Pre-pull docker images so first boot has zero-pull start.
  provisioner "shell" {
    environment_vars = [
      "IMAGE_REGISTRY=${var.image_registry}",
      "IMAGE_TAG=${var.image_tag}",
      "BUILD_REGION=${var.build_region}",
    ]
    script = "${path.root}/scripts/pull-images.sh"
  }

  # 7. Finalize permissions + clean up.
  provisioner "shell" {
    inline = [
      "sudo chmod 755 /opt/cast-clone/bootstrap.sh",
      "sudo chown -R root:root /opt/cast-clone /etc/cast-clone",
      "sudo dnf clean all",
      "sudo rm -rf /var/cache/dnf/* /tmp/* /var/tmp/*",
      "sudo rm -f /home/ec2-user/.bash_history /root/.bash_history",
    ]
  }

  # 8. Manifest with one AMI ID per region — consumed by update-cfn-mappings.sh.
  post-processor "manifest" {
    output     = "manifest.json"
    strip_path = true
    custom_data = {
      version        = var.version
      image_tag      = var.image_tag
      image_registry = var.image_registry
    }
  }
}
