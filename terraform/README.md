# Using Terraform



### Sub-directories and state files
Each subdirectory under the `terraform/` directory contains an isolated set of terraform configuration files, with the expectation of a few symlinked files, and has a separate state file associated with it.  State files are stored with in S3 under the bucket titled `tfstate`.

### Clone git

`git clone git@github.com:mozilla-releng/build-cloud-tools.git`


### Initial setup

If you haven't done so previously, you must first run `terraform init` for each subdirectory you intend to run terraform in.  This only needs to be run once on your local subdirectory in order to setup the local state files and download any missing modules.  As the terraform documentation states, `terraform init` is idempotent so it should be safe to run multiple times under the same subdirectory

The following initializes the base subdirectory

    cd terraform/base`
    terraform init


### Test the current state and the master branch
Before making any changes, it is a good idea to ensure the configuration files in the master branch match that which currently exists in AWS.  This can be done with `terraform plan`.  `terraform plan` is a non-destructive action.  It validates and parsers the terraform config files within the local directory, then queries the AWS api to determine the state of the resources defined locally.  If all the resources and their defined state exist and match the local terraform configs, there should be no changes proposed.  If there is any discrepancy, terraform will return a planned set of actions to either create, destroy or modify resources in AWS.

    cd terraform/base
    terraform plan

##### If state doesn't match the master branch

If you have the most recent copy of the git master branch and `terraform plan` shows it wants to make changes, then someone may have applied changes to production without pushing them to the masters branch.  If this happens, you will need to find who made the changes and request them to be submitted for review and merged for continuing.  Best practices dictates you should never apply changes before having changes reviewed and merged to master.

### Apply changes
If you make changes to the local terraform config files and test the proposed changes with `terraform plan`, you can then apply them and let terraform make the proposed changes to AWS with `terraform apply`.  This action can be destructive so make sure you review the changes.  `terraform apply` will produce a proposed manifest of changes similar to `terraform plan` except, it will also ask if you want to apply the changes.  You must input yes or no.

    cd terraform/base
    terraform apply

