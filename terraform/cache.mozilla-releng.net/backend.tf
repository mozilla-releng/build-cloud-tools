terraform {
  backend "s3" {
    bucket = "tf-base"
    key    = "tf_state/cache_mozilla-releng_net/terraform.tfstate"
    region = "us-east-1"
  }
}

data "terraform_remote_state" "cache_mozilla-releng_net" {
    backend = "s3"
    config {
        bucket = "tf-base"
        key = "tf_state/cache_mozilla-releng_net/terraform.tfstate"
        region = "us-east-1"
    }
}
