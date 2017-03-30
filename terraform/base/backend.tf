# As of 0.9.0, remote state is configured through the new backend system
# See https://www.terraform.io/docs/backends/legacy-0-8.html

terraform {
  backend "s3" {
    bucket = "tf-base"
    key    = "tf_state/base/terraform.tfstate"
    region = "us-east-1"
  }
}
