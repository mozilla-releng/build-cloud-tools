# Route 53 resources

# Hosted Zone for mozilla-releng.net
resource "aws_route53_zone" "mozilla-releng" {
    name = "mozilla-releng.net."
}

# A list of CNAMEs for heroku apps
variable "heroku_cnames" {
    default = ["archiver",
               "archiver.staging",
               "clobberer",
               "clobberer.staging",
               "dashboard.shipit",
               "dashboard.shipit.staging",
               "mapper",
               "mapper.staging",
               "tooltool",
               "tooltool.staging",
               "treestatus",
               "treestatus.staging"]
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

