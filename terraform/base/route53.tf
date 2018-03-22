# Route 53 resources

# Hosted Zone for mozilla-releng.net
resource "aws_route53_zone" "mozilla-releng" {
    name = "mozilla-releng.net."
}

##################################
## Heroku production app cnames ##
##################################

resource "aws_route53_record" "heroku-coalease-cname" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "coalesce.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["oita-54541.herokussl.com"]
}
resource "aws_route53_record" "heroku-archiver-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "archiver.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["archiver.mozilla-releng.net.herokudns.com"]
}
resource "aws_route53_record" "heroku-clobberer-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "clobberer.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["saitama-70467.herokussl.com"]
}
resource "aws_route53_record" "heroku-mapper-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "mapper.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["mapper.mozilla-releng.net.herokudns.com"]
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
    records = ["treestatus.mozilla-releng.net.herokudns.com"]
}


###############################
## Heroku staging app cnames ##
###############################

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
resource "aws_route53_record" "heroku-treestatus-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "treestatus.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["nagasaki-25852.herokussl.com"]
}
resource "aws_route53_record" "heroku-tooltool-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tooltool.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["shizuoka-60622.herokussl.com"]
}


#########################################
## Heroku Shipit production app cnames ##
#########################################

resource "aws_route53_record" "heroku-dashboard-shipit-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "dashboard.shipit.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["dashboard.shipit.mozilla-releng.net.herokudns.com"]
}
resource "aws_route53_record" "heroku-pipeline-shipit-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "pipeline.shipit.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["pipeline.shipit.mozilla-releng.net.herokudns.com"]
}
resource "aws_route53_record" "heroku-signoff-shipit-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "signoff.shipit.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["signoff.shipit.mozilla-releng.net.herokudns.com"]
}
resource "aws_route53_record" "heroku-taskcluster-shipit-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "taskcluster.shipit.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["taskcluster.shipit.mozilla-releng.net.herokudns.com"]
}
resource "aws_route53_record" "heroku-uplift-shipit-cname-prod" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "uplift.shipit.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["uplift.shipit.mozilla-releng.net.herokudns.com"]
}


######################################
## Heroku Shipit staging app cnames ##
######################################

resource "aws_route53_record" "heroku-dashboard-shipit-cname-stage" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "dashboard.shipit.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["dashboard.shipit.staging.mozilla-releng.net.herokudns.com"]
}
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

############################
## CloudFront CDN aliases ##
############################

variable "cloudfront_alias" {
    default = ["docs",
               "docs.staging",
               "shipit",
               "shiptit.staging",
               "www",
               "staging"]
}

# Cloudfront Alias Targets
# In the future, these may be sourced directly from terraform cloudfront resources
# should we decide to manage cloudfronts in terraform
variable "cloudfront_alias_domain" {
    type = "map"
    default = {
        docs = "d1945er7u4liht"
        docs.staging = "d32jt14rospqzr"
        shipit = "dve8yd1431ifz"
        shiptit.staging = "d2ld4e8bl8yd1l"
        www = "d1qqwps52z1e12"
        staging = "dpwmwa9tge2p3"
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

