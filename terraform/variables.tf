# Global variables

variable "base_bucket" {
    description = "S3 bucket for storing terraform state, ssh pub keys, etc"
    default = "tf-base"
}
