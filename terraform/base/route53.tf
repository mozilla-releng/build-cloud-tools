# Route 53 resources

resource "aws_route53_zone" "mozilla-releng" {
    name = "mozilla-releng.net."
}

resource "aws_route53_zone" "moztools" {
    name = "moz.tools"
}

#############################
##  moz.tools other cnames ##
#############################

resource "aws_route53_record" "relman-ci-moz-tools-cname-prod" {
  zone_id = "${aws_route53_zone.moztools.zone_id}"
  name = "relman-ci.moz.tools"
  type = "A"
  ttl = "180"
  records = ["35.180.7.143"]
}

resource "aws_route53_record" "relman-clouseau-moz-tools-cname-prod" {
  zone_id = "${aws_route53_zone.moztools.zone_id}"
  name = "clouseau.moz.tools"
  type = "CNAME"
  ttl = "180"
  records = ["clouseau.moz.tools.herokudns.com"]
}

#########################################
## Heroku releng production app cnames ##
#########################################

resource "aws_route53_record" "heroku-coalease-cname" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "coalesce.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["oita-54541.herokussl.com"]
}

resource "aws_route53_record" "heroku-mapper-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "mapper.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["mapper.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-notification-identity-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "identity.notification.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["identity.notification.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-notification-policy-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "policy.notification.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["policy.notification.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-tokens-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tokens.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["tokens.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-tooltool-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tooltool.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["kochi-11433.herokussl.com"]
}

resource "aws_route53_record" "heroku-treestatus-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "treestatus.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["kochi-31413.herokussl.com"]
}

######################################
## Heroku releng staging app cnames ##
######################################

resource "aws_route53_record" "heroku-workflow-ui-shipit-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "shipit-ui-workflow.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["shipit-ui-workflow.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-archiver-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "archiver.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["archiver.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-clobberer-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "clobberer.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["saitama-70467.herokussl.com"]
}

resource "aws_route53_record" "heroku-mapper-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "mapper.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["mapper.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-notification-identity-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "identity.notification.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["identity.notification.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-notification-policy-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "policy.notification.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["policy.notification.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-tokens-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tokens.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["tokens.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-tooltool-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tooltool.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["shizuoka-60622.herokussl.com"]
}

resource "aws_route53_record" "heroku-treestatus-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "treestatus.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["nagasaki-25852.herokussl.com"]
}

######################################
## Heroku releng testing app cnames ##
######################################

resource "aws_route53_record" "heroku-archiver-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "archiver.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["archiver.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-clobberer-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "clobberer.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["saitama-70467.herokussl.com"]
}

resource "aws_route53_record" "heroku-mapper-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "mapper.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["mapper.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-notification-identity-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "identity.notification.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["identity.notification.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-notification-policy-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "policy.notification.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["policy.notification.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-tokens-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tokens.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["tokens.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-tooltool-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tooltool.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["shizuoka-60622.herokussl.com"]
}

resource "aws_route53_record" "heroku-treestatus-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "treestatus.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["treestatus.testing.mozilla-releng.net.herokudns.com"]
}

#########################################
## Heroku relman production app cnames ##
#########################################

resource "aws_route53_record" "heroku-code-coverage-backend-shipit-cname-prod" {
    zone_id = "${aws_route53_zone.moztools.zone_id}"
    name = "coverage.moz.tools"
    type = "CNAME"
    ttl = "180"
    records = ["coverage.moz.tools.herokudns.com"]
}

######################################
## Heroku relman staging app cnames ##
######################################

resource "aws_route53_record" "heroku-code-coverage-backend-shipit-cname-stage" {
    zone_id = "${aws_route53_zone.moztools.zone_id}"
    name = "coverage.staging.moz.tools"
    type = "CNAME"
    ttl = "180"
    records = ["coverage.staging.moz.tools.herokudns.com"]
}

######################################
## Heroku relman testing app cnames ##
######################################

resource "aws_route53_record" "heroku-code-coverage-backend-shipit-cname-test" {
    zone_id = "${aws_route53_zone.moztools.zone_id}"
    name = "coverage.testing.moz.tools"
    type = "CNAME"
    ttl = "180"
    records = ["coverage.testing.moz.tools.herokudns.com"]
}

#########################################
## Heroku shipit production app cnames ##
#########################################

resource "aws_route53_record" "heroku-uplift-shipit-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "uplift.shipit.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["uplift.shipit.mozilla-releng.net.herokudns.com"]
}

######################################
## Heroku shipit staging app cnames ##
######################################

resource "aws_route53_record" "heroku-pipeline-shipit-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "pipeline.shipit.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["pipeline.shipit.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-signoff-shipit-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "signoff.shipit.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["signoff.shipit.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-taskcluster-shipit-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "taskcluster.shipit.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["taskcluster.shipit.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-uplift-shipit-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "uplift.shipit.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["uplift.shipit.staging.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-workflow-shipit-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "shipit-workflow.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["shipit-workflow.staging.mozilla-releng.net.herokudns.com"]
}

######################################
## Heroku shipit testing app cnames ##
######################################

resource "aws_route53_record" "heroku-pipeline-shipit-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "pipeline.shipit.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["pipeline.shipit.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-signoff-shipit-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "signoff.shipit.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["signoff.shipit.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-taskcluster-shipit-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "taskcluster.shipit.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["taskcluster.shipit.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-uplift-shipit-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "uplift.shipit.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["uplift.shipit.testing.mozilla-releng.net.herokudns.com"]
}

resource "aws_route53_record" "heroku-workflow-shipit-cname-test" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "shipit-workflow.testing.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["shipit-workflow.testing.mozilla-releng.net.herokudns.com"]
}

############################
## CloudFront CDN aliases ##
############################

variable "cloudfront_alias" {
    default = ["docs",
               "docs.staging",
               "docs.testing",
               "shipit",
               "shipit.staging",
               "shipit.testing",
               "staging",
               "testing",
               "www"]
}

variable "cloudfront_moztools_alias" {
    default = ["static-analysis",
               "static-analysis.staging",
               "static-analysis.testing",
               "uplift",
               "uplift.staging",
               "uplift.testing"]
}

# Cloudfront Alias Targets
# In the future, these may be sourced directly from terraform cloudfront resources
# should we decide to manage cloudfronts in terraform
variable "cloudfront_alias_domain" {
    type = "map"
    default = {
        docs = "d1945er7u4liht"
        docs.staging = "d32jt14rospqzr"
        docs.testing = "d1sw5c8kdn03y"
        shipit = "dve8yd1431ifz"
        shipit.staging = "d2ld4e8bl8yd1l"
        shipit.testing = "d2jpisuzgldax2"
        staging = "dpwmwa9tge2p3"
        testing = "d1l70lpksx3ik7"
        www = "d1qqwps52z1e12"
    }
}

variable "cloudfront_moztools_alias_domain" {
    type = "map"
    default = {
        static-analysis = "d2ezri92497z3m"
        static-analysis.staging = "d21hzgxp28m0tc"
        static-analysis.testing = "d1blqs705aw8h9"
        uplift = "d2j55he28msyhx"
        uplift.staging = "d3voyguhnvtgyb"
        uplift.testing = "d1swet7sulei5z"
    }
}

# A (Alias) records for cloudfront apps
resource "aws_route53_record" "cloudfront-alias" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "${element(var.cloudfront_alias, count.index)}.mozilla-releng.net"
    type = "A"
    count = "${length(var.cloudfront_alias)}"

    alias {
        name = "${var.cloudfront_alias_domain[element(var.cloudfront_alias, count.index)]}.cloudfront.net."
        zone_id = "Z2FDTNDATAQYW2"
        evaluate_target_health = false
    }
}

resource "aws_route53_record" "cloudfront-moztools-alias" {
    zone_id = "${aws_route53_zone.moztools.zone_id}"
    name = "${element(var.cloudfront_moztools_alias, count.index)}.moz.tools"
    type = "A"
    count = "${length(var.cloudfront_moztools_alias)}"

    alias {
        name = "${var.cloudfront_moztools_alias_domain[element(var.cloudfront_moztools_alias, count.index)]}.cloudfront.net."
        zone_id = "Z2FDTNDATAQYW2"
        evaluate_target_health = false
    }
}

# A special root alias that points to www.mozilla-releng.net
resource "aws_route53_record" "root-alias" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "mozilla-releng.net"
    type = "A"

    alias {
        name = "www.mozilla-releng.net"
        zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
        evaluate_target_health = false
    }
}

# Ship-it production instance, hosted by CloudOps
resource "aws_route53_record" "dockerflow-shipit-api-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name= "shipit-api.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["shipitbackend-default.prod.mozaws.net"]
}
