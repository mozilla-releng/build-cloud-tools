# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

#
# Terraform config for setting up cache.mozilla-releng.net cloudfront
#

# Create data source for ssl cert
data "aws_acm_certificate" "cache_cert" {
    domain   = "cache.mozilla-releng.net"
    statuses = ["ISSUED"]
}

# Create data source for mozilla-releng.net host zone
data "aws_route53_zone" "mozilla_releng_net" {
    name         = "mozilla-releng.net."
}

# s3 bucket resource for the orgin bucket
resource "aws_s3_bucket" "releng-cache" {
    bucket = "releng-cache"
    acl = "public-read"

    tags {
	Name        = "releng-cache"
        Environment = "production"
	Management  = "Terraform"
    }
}

resource "aws_cloudfront_distribution" "releng_cache_s3_distribution" {
    origin {
      domain_name = "${aws_s3_bucket.releng-cache.bucket_domain_name}"
      origin_id   = "s3-releng-cache"

    }

    enabled             = true
    is_ipv6_enabled     = false
    comment             = "Managed by Terraform. See build-cloud-tools"
    aliases = ["cache.mozilla-releng.net"]

    default_cache_behavior {
        allowed_methods  = ["GET", "HEAD"]
        cached_methods   = ["GET", "HEAD"]
        target_origin_id = "s3-releng-cache"

        forwarded_values {
            query_string = false

            cookies {
                forward = "none"
            }
        }

        # This viewer policy enables the http->https 301 redirect
        viewer_protocol_policy = "redirect-to-https"
        min_ttl                = 0
        default_ttl            = 3600
        max_ttl                = 86400
    }

    price_class = "PriceClass_All"

    restrictions {
        geo_restriction {
            restriction_type = "none"
        }
    }

    tags {
	Name        = "releng_cache_s3_distribution"
        Environment = "production"
	Management  = "Terraform"
    }

    viewer_certificate {
        acm_certificate_arn = "${data.aws_acm_certificate.cache_cert.arn}"
        minimum_protocol_version = "TLSv1"
        ssl_support_method = "sni-only"
    }
}

# Create an A record with Alias type
resource "aws_route53_record" "cache_mozilla_releng_net" {
    zone_id = "${data.aws_route53_zone.mozilla_releng_net.zone_id}"
    name = "cache.mozilla-releng.net"
    type = "A"

    alias {
        name = "${aws_cloudfront_distribution.releng_cache_s3_distribution.domain_name}"
	# This zone_id is universal for *ALL* cloud front distributions
        zone_id = "Z2FDTNDATAQYW2"
        evaluate_target_health = false
    }
}

