# CloudFormation Templates

This directory contains a number of [CloudFormation templates](http://aws.amazon.com/documentation/cloudformation/) expressed in [cfn-pyplates](https://cfn-pyplates.readthedocs.org/en/latest/) format.
Taken together, these templates define the releng cloud infrastructure.

The templates are tied to stacks and to one another with `stacks.yml`.
See that file for a list of stacks that can be deployed.

## Deploying

To deploy a stack, use the `aws_deploy_cloudformation` script in this repo:

    aws_deploy_cloudformation --wait MyStackName

The script has a number of other options; see its `--help` for details.

## Hacking

### Stacks

The format of `stacks.yml` is as follows:

 * `stacks`

    * *Stack name* -- note that these must be unique across all regions.
      Since most stacks will be duplicated in all regions, add a short region suffix (`Usw1`, `Usw2`, or `Use1`) to the stack name.

      * `region`: *region name* -- the long region name in which this stack is deployed (e.g., `us-east-1`)
      * `template`: *template filename* -- the filename of the template that defines this stack
      * `options`: *option dictionary* -- an arbitrary dictionary that will be available to the template as `options`.
        This is *not* the same thing as parameters, although it is often more useful; see the pyplates documentation for details.
        See "Inter-stack References" below, too.

#### Inter-stack References

Stacks often refer to resources in other stacks.
Rather than hard-code these correspondances, the tools can look them up for you.
Any option which has sub-keys `stack` and `resource` will be looked up before the template is generated.
For example, to get the releng VPC's id, use

```
    options:
        vpcid:
            stack: RelengNetworkUsw1
            resource: RelengVPC
```

then refer to this resource as `options['vpcid']` in the template body.

Note that this system uses a "live" lookup of the resource name when the template is deployed.
At that time, the reference is converted into a static resource id and encoded into the template.

### Future Plans

 * Support for parameters
 * Automatic region suffixes

### Templates

To modify the templates themselves, you'll need to know Python and [cfn-pyplates](https://cfn-pyplates.readthedocs.org/en/latest/).
We do a few things "uniquely", though:

 * All Python objects should be explicitly imported (this keeps flake8 happy)
 * In many cases, objects are created by Python code, rather than being listed out.
   [Dont' repeat yourself](http://en.wikipedia.org/wiki/Don%27t_repeat_yourself).
   This makes the templates a little harder for a non-Pythonista to read, but that's OK.
