# Creates a cloudtrail for sending aws logs to foxsec

resource "aws_cloudtrail" "cloudtrail" {
    name = "cloudtrail-to-foxsec"
    s3_bucket_name = "moz-cloudtrail-logs"
    s3_key_prefix = "mozilla-releng"
    include_global_service_events = true
    is_multi_region_trail = true
    tags {
        Name = "cloudtrail-to-foxsec"
    }
}
