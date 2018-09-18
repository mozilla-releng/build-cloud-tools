resource "aws_vpn_gateway" "vpn_gw_usw1" {
  provider = "aws.us-west-1"

  tags {
    Name = "USW1 VPN Gateway"
    terraform_managed = "True"
    repo_url = "https://github.com/mozilla-releng/build-cloud-tools"
  }
}

resource "aws_customer_gateway" "cgw_usw1_mdc1" {
  provider = "aws.us-west-1"
  bgp_asn    = 65048
  ip_address = "63.245.208.251"
  type       = "ipsec.1"

  tags {
    Name = "MDC1 Customer Gateway"
    terraform_managed = "True"
    repo_url = "https://github.com/mozilla-releng/build-cloud-tools"
  }

}
resource "aws_customer_gateway" "cgw_usw1_mdc2" {
  provider = "aws.us-west-1"
  bgp_asn    = 65050
  ip_address = "63.245.210.251"
  type       = "ipsec.1"

  tags {
    Name = "MDC2 Customer Gateway"
    terraform_managed = "True"
    repo_url = "https://github.com/mozilla-releng/build-cloud-tools"
  }

}

resource "aws_vpn_connection" "vpn_connection_usw1_mdc1" {
  provider = "aws.us-west-1"
  vpn_gateway_id      = "${aws_vpn_gateway.vpn_gw_usw1.id}"
  customer_gateway_id = "${aws_customer_gateway.cgw_usw1_mdc1.id}"
  type                = "ipsec.1"

  tags {
    Name = "USW1-MDC1"
    terraform_managed = "True"
    repo_url = "https://github.com/mozilla-releng/build-cloud-tools"
  }
}

resource "aws_vpn_connection" "vpn_connection_usw1_mdc2" {
  provider = "aws.us-west-1"
  vpn_gateway_id      = "${aws_vpn_gateway.vpn_gw_usw1.id}"
  customer_gateway_id = "${aws_customer_gateway.cgw_usw1_mdc2.id}"
  type                = "ipsec.1"

  tags {
    Name = "USW1-MDC2"
    terraform_managed = "True"
    repo_url = "https://github.com/mozilla-releng/build-cloud-tools"
  }
}

