# This file contains empty declarations for variables that will be definied in each
# environments terraform.tfvars file

variable "profile" {
    description = "Name of the AWS profile to grab credentials from"
}

variable "region" {
    description = "The AWS region to create things in."
}

variable "env" {
    description = "Environment name"
}
