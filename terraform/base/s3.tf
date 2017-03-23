resource "aws_s3_bucket" "base_bucket" {
    bucket = "${var.base_bucket}"
    acl = "private"
    versioning {
        enabled = true
    }
}
