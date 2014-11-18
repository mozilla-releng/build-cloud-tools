import unittest
import mock
import boto
import cloudtools.aws.spot


class TestPopulateSpotCache(unittest.TestCase):

    def test_no_reqest_ids(self):
        with mock.patch("cloudtools.aws.spot.get_aws_connection") as conn:
            cloudtools.aws.spot.populate_spot_requests_cache("region-a")
            conn.assert_has_calls(
                [mock.call().get_all_spot_instance_requests()])

    def test_with_reqest_ids(self):
        with mock.patch("cloudtools.aws.spot.get_aws_connection") as conn:
            cloudtools.aws.spot.populate_spot_requests_cache(
                "region-a", request_ids=[1, 2])
            conn.assert_has_calls(
                [mock.call().get_all_spot_instance_requests(
                    request_ids=[1, 2])])

    @mock.patch("cloudtools.aws.spot.get_aws_connection")
    def test_invalid_request_id(self, conn):
        req = mock.Mock()
        req.id = "id-1"
        conn.return_value.get_all_spot_instance_requests.side_effect = \
            [boto.exception.EC2ResponseError("404", "reason"), [req]]
        cloudtools.aws.spot.populate_spot_requests_cache("r-1", ["id-1"])
        expected_calls = [
            mock.call(request_ids=["id-1"]),
            mock.call()
        ]
        conn.return_value.get_all_spot_instance_requests.assert_has_called(
            expected_calls)
        self.assertDictEqual({("r-1", "id-1"): req},
                             cloudtools.aws.spot._spot_requests)


class TestGetSpotRequest(unittest.TestCase):

    def setUp(self):
        # reset the cahches
        reload(cloudtools.aws.spot)

    @mock.patch("cloudtools.aws.spot.populate_spot_requests_cache")
    def test_not_cached(self, m_populate_spot_requests_cache):
        cloudtools.aws.spot.get_spot_request("region-1", "id-1")
        m_populate_spot_requests_cache.assert_called_once_with("region-1")

    @mock.patch("cloudtools.aws.spot.get_aws_connection")
    def test_cached(self, m_get_aws_conn):
        req = mock.Mock()
        req.id = "id-1"
        m_get_aws_conn.return_value. \
            get_all_spot_instance_requests.return_value = [req]
        cloudtools.aws.spot.get_spot_request("region-1", "id-1")
        cloudtools.aws.spot.get_spot_request("region-1", "id-1")
        m_get_aws_conn.assert_called_once_with("region-1")


class TestGetInstancesToTag(unittest.TestCase):

    @mock.patch("cloudtools.aws.spot.get_spot_instances")
    def test_no_tags(self, m_get_spot_instances):
        i = mock.Mock()
        i.tags = {}
        m_get_spot_instances.return_value = [i]
        self.assertEqual(cloudtools.aws.spot.get_instances_to_tag("r-1"), [i])

    @mock.patch("cloudtools.aws.spot.get_spot_instances")
    def test_all_tags(self, m_get_spot_instances):
        i = mock.Mock()
        i.tags = {"Name": "n1", "FQDN": "fqdn1", "moz-type": "t1",
                  "moz-state": "s1"}
        m_get_spot_instances.return_value = [i]
        self.assertEqual(cloudtools.aws.spot.get_instances_to_tag("r-1"), [])

    @mock.patch("cloudtools.aws.spot.get_spot_instances")
    def test_some_tags(self, m_get_spot_instances):
        i = mock.Mock()
        i.tags = {"Name1": "n1", "FQDN": "fqdn1", "moz-type": "t1",
                  "moz-state": "s1"}
        m_get_spot_instances.return_value = [i]
        self.assertEqual(cloudtools.aws.spot.get_instances_to_tag("r-1"), [i])
