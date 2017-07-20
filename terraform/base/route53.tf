# Route 53 resources

# Hosted Zone for mozilla-releng.net
resource "aws_route53_zone" "mozilla-releng" {
    name = "mozilla-releng.net."
}

# A list of CNAMEs for heroku apps
variable "heroku_cnames" {
    default = ["archiver",
               "archiver.staging",
               "clobberer.staging",
               "dashboard.shipit",
               "dashboard.shipit.staging",
               "mapper",
               "mapper.staging",
               "treestatus.staging",
               "pipeline.shipit",
               "pipeline.shipit.staging",
               "signoff.shipit",
               "signoff.shipit.staging",
               "taskcluster.shipit",
               "taskcluster.shipit.staging",
               "uplift.shipit",
               "uplift.shipit.staging"]
}

# CNAME records for heroku apps
resource "aws_route53_record" "heroku-cname" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "${element(var.heroku_cnames, count.index)}.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    count = "${length(var.heroku_cnames)}"
    records = ["${element(var.heroku_cnames, count.index)}.mozilla-releng.net.herokudns.com"]
}

# Coalesce app cname is unique because it uses the old ssl endpoint
resource "aws_route53_record" "heroku-coalease-cname" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "coalesce.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["oita-54541.herokussl.com"]
}

# Tooltool app cname uses non-sni ssl due to old versions of python
# used during the build process
# See bug 1380177
resource "aws_route53_record" "heroku-tooltool-cname" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tooltool.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["kochi-11433.herokussl.com"]
}

resource "aws_route53_record" "heroku-tooltool-staging-cname" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "tooltool.staging.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["shizuoka-60622.herokussl.com"]
}

# Treestatus app cname uses non-sni ssl due to old versions of python
# used during the build process
# See bug 1380177
resource "aws_route53_record" "heroku-treestatus-cname" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "treestatus.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["osaka-77459.herokussl.com"]
}

# Clobberer app cname uses non-sni ssl due to old versions of python
# used during the build process
# See bug 1380177
resource "aws_route53_record" "heroku-clobberer-cname" {
    zone_id = "${aws_route53_zone.mozilla-releng.zone_id}"
    name = "clobberer.mozilla-releng.net"
    type = "CNAME"
    ttl = "180"
    records = ["saitama-70467.herokussl.com"]
}

# Cloudfront Alias names
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

