"""
DNS 解析引擎与域名转 IP 业务编排单元测试
"""

import unittest
from crawler.dns_resolver import (
    build_dns_query_packet,
    parse_dns_name,
    is_valid_public_ip,
    DNSResolver
)
from crawler.domains2ip import (
    DomainSourceNode,
    Domains2IPNode,
    DomainsToIPEngine
)
from crawler.geo import GeoInfo


class TestDNSResolverAndDomains2IP(unittest.TestCase):
    def test_build_dns_query_packet(self):
        pkt = build_dns_query_packet("example.com", qtype=1)
        self.assertGreater(len(pkt), 12)
        self.assertTrue(b"example" in pkt)
        self.assertTrue(b"com" in pkt)

    def test_is_valid_public_ip(self):
        # 公网 IP
        self.assertTrue(is_valid_public_ip("104.18.34.111"))
        self.assertTrue(is_valid_public_ip("1.1.1.1"))
        self.assertTrue(is_valid_public_ip("2606:4700::1111"))

        # 私有与保留地址
        self.assertFalse(is_valid_public_ip("127.0.0.1"))
        self.assertFalse(is_valid_public_ip("192.168.1.1"))
        self.assertFalse(is_valid_public_ip("10.0.0.1"))
        self.assertFalse(is_valid_public_ip("::1"))
        self.assertFalse(is_valid_public_ip("invalid_ip"))

    def test_parse_domain_line(self):
        line = "11.cf.3666888.xyz:443#vps789-CA-加拿大 多伦多-118ms-14.50mb/s"
        parsed = DomainsToIPEngine.parse_domain_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.domain, "11.cf.3666888.xyz")
        self.assertEqual(parsed.port, 443)
        self.assertEqual(parsed.latency, 118)
        self.assertAlmostEqual(parsed.speed, 14.50)

    def test_parse_domain_line_no_port(self):
        line = "cf-cname.xingpingcn.top#vps789-US-美国-120ms-14.40mb/s"
        parsed = DomainsToIPEngine.parse_domain_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.domain, "cf-cname.xingpingcn.top")
        self.assertEqual(parsed.port, 443)
        self.assertEqual(parsed.latency, 120)
        self.assertAlmostEqual(parsed.speed, 14.40)

    def test_domains2ip_node_formatting(self):
        geo = GeoInfo(country_code="CA", country="加拿大", city="多伦多")
        node_v4 = Domains2IPNode(
            ip="104.18.34.111",
            port=443,
            latency=118,
            speed=14.5,
            is_ipv6=False,
            geo=geo
        )
        self.assertEqual(
            node_v4.formatted_line,
            "104.18.34.111:443#vps789-CA-加拿大 多伦多-118ms-14.50mb/s"
        )

        node_v6 = Domains2IPNode(
            ip="2606:4700::1111",
            port=443,
            latency=120,
            speed=10.0,
            is_ipv6=True,
            geo=GeoInfo(country_code="US", country="美国", city="")
        )
        self.assertEqual(
            node_v6.formatted_line,
            "[2606:4700::1111]:443#vps789-US-美国-120ms-10.00mb/s"
        )


if __name__ == "__main__":
    unittest.main()
