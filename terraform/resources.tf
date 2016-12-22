# This file contains shared global resources

# Configure remote state
# Outputs can be accessed via ${data.terraform_remote_state.base.output_name}
data "terraform_remote_state" "base" {
    backend = "s3"
    config {
        encrypt = true
        acl = "private"
        bucket = "${var.base_bucket}"
        region = "us-east-1"
        key = "tf_state/base/terraform.tfstate"
    }
}
