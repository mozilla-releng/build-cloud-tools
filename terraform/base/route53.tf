# Route 53 resources

resource "aws_route53_zone" "moztools" {
    name = "moz.tools."
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

resource "aws_route53_record" "relman-buildhub-moz-tools-cname-prod" {
  zone_id = "${aws_route53_zone.moztools.zone_id}"
  name = "buildhub.moz.tools"
  type = "CNAME"
  ttl = "180"
  records = ["prod.buildhub2.prod.cloudops.mozgcp.net"]
}

resource "aws_route53_record" "relman-buildhub-moz-tools-cert-prod" {
  zone_id = "${aws_route53_zone.moztools.zone_id}"
  name = "_1cd7d55cbecc43cd936b8a83293e002d.buildhub.moz.tools"
  type = "CNAME"
  ttl = "180"
  records = ["dcv.digicert.com"]
}

resource "aws_route53_record" "relman-coverity-moz-tools-cname-prod" {
  zone_id = "${aws_route53_zone.moztools.zone_id}"
  name = "coverity.moz.tools"
  type = "CNAME"
  ttl = "180"
  records = ["prod.coverity.prod.cloudops.mozgcp.net"]
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

resource "aws_route53_record" "heroku-event-listener-cname-prod" {
    zone_id = "${aws_route53_zone.moztools.zone_id}"
    name = "eventlistener.moz.tools"
    type = "CNAME"
    ttl = "180"
    records = ["convex-woodland-ilwk96s11s92e5otfkmb5ybe.herokudns.com"]
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

resource "aws_route53_record" "heroku-event-listener-cname-stage" {
    zone_id = "${aws_route53_zone.moztools.zone_id}"
    name = "eventlistener.staging.moz.tools"
    type = "CNAME"
    ttl = "180"
    records = ["immense-refuge-f4ii4ur88iq0x707ybzq5mfn.herokudns.com"]
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

resource "aws_route53_record" "heroku-event-listener-cname-test" {
    zone_id = "${aws_route53_zone.moztools.zone_id}"
    name = "eventlistener.testing.moz.tools"
    type = "CNAME"
    ttl = "180"
    records = ["adjacent-shelf-2mxct7inb0tl5tg1rwt73ev4.herokudns.com"]
}

############################
## CloudFront CDN aliases ##
############################

variable "cloudfront_moztools_alias" {
    default = ["static-analysis",
               "static-analysis.staging",
               "static-analysis.testing"]
}

variable "cloudfront_moztools_alias_domain" {
    type = "map"
    default = {
        static-analysis = "d2ezri92497z3m"
        static-analysis.staging = "d21hzgxp28m0tc"
        static-analysis.testing = "d1blqs705aw8h9"
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
