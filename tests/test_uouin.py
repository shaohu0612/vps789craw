"""
UOUIN 麒麟优选节点采集与格式化单元测试
"""

import hashlib
import pytest
from unittest.mock import MagicMock, patch

from crawler.uouin import (
    UOUINCrawler,
    UOUINRawNode,
    GeoInfo,
    GeoResolver,
    LINE_NAME_MAP,
)


def test_generate_signature():
    """测试 UOUIN 动态 MD5 签名生成算法"""
    fixed_time = 1771937000000
    time_ms, hash_val = UOUINCrawler.generate_signature(now_ms=fixed_time)
    assert time_ms == fixed_time
    assert len(hash_val) == 32

    # 手动验算
    s1 = hashlib.md5("DdlTxtN0sUOu".encode("utf-8")).hexdigest()
    s2 = f"{s1}70cloudflareapikey{fixed_time}"
    expected = hashlib.md5(s2.encode("utf-8")).hexdigest()
    assert hash_val == expected


def test_parse_numeric_speed_and_latency():
    """测试速度与延迟数值提取"""
    assert UOUINCrawler.parse_numeric_speed("61.14mb/s") == 61.14
    assert UOUINCrawler.parse_numeric_speed("10.00MB/s") == 10.0
    assert UOUINCrawler.parse_numeric_speed("0.14mb/s") == 0.14
    assert UOUINCrawler.parse_numeric_speed("") == 0.0
    assert UOUINCrawler.parse_numeric_speed("invalid") == 0.0

    assert UOUINCrawler.parse_numeric_latency("51.97ms") == 51.97
    assert UOUINCrawler.parse_numeric_latency("120ms") == 120.0
    assert UOUINCrawler.parse_numeric_latency("") == 9999.0


def test_geo_resolver_translations():
    """测试国家与城市名称中文化翻译"""
    resolver = GeoResolver()

    # 国家翻译
    assert resolver.translate_country("United States", "US") == "美国"
    assert resolver.translate_country("Canada", "CA") == "加拿大"
    assert resolver.translate_country("United Kingdom", "GB") == "英国"
    assert resolver.translate_country("Hong Kong", "HK") == "香港"
    assert resolver.translate_country("-", "JP") == "日本"
    assert resolver.translate_country("UnknownCountry", "ZZ") == "UnknownCountry"

    # 城市翻译
    assert resolver.translate_city("San Jose") == "圣何塞"
    assert resolver.translate_city("Toronto") == "多伦多"
    assert resolver.translate_city("London") == "伦敦"
    assert resolver.translate_city("Tokyo") == "东京"
    assert resolver.translate_city("Hong Kong") == "香港"
    assert resolver.translate_city("New York City") == "纽约"


def test_format_node_line_ipv4_and_ipv6():
    """测试格式化节点行 (IPv4 与 IPv6，带默认端口 443)"""
    # IPv4 节点
    node_v4 = UOUINRawNode(
        ip="172.64.229.121",
        line="电信",
        loss="0.00%",
        ping="51.97ms",
        speed_str="61.14mb/s",
        speed_value=61.14,
        latency_value=51.97,
        bandwidth="489.12mb"
    )
    geo_v4 = GeoInfo(country_code="CA", country="加拿大", city="多伦多")
    line_v4 = UOUINCrawler.format_node_line(node_v4, geo_v4, default_port=443)
    assert line_v4 == "172.64.229.121:443#麒麟优选-电信-CA-加拿大 多伦多-51.97ms-61.14mb/s"

    # IPv6 节点
    node_v6 = UOUINRawNode(
        ip="2a06:98c1:310e:588a:83f7:dc81:a024:33b7",
        line="IPV6",
        loss="0.00%",
        ping="45.67ms",
        speed_str="30.38mb/s",
        speed_value=30.38,
        latency_value=45.67,
        bandwidth="243.04mb"
    )
    geo_v6 = GeoInfo(country_code="GB", country="英国", city="伦敦")
    line_v6 = UOUINCrawler.format_node_line(node_v6, geo_v6, default_port=443)
    assert line_v6 == "[2a06:98c1:310e:588a:83f7:dc81:a024:33b7]:443#麒麟优选-IPV6-GB-英国 伦敦-45.67ms-30.38mb/s"


def test_extract_raw_nodes_filtering_and_dedup():
    """测试节点速度筛选 (>= 10mb/s)、私网过滤与去重"""
    crawler = UOUINCrawler()
    mock_data = {
        "ctcc": {
            "info": [
                {"ip": "172.64.229.121", "speed": "61.14mb/s", "ping": "51.97ms", "loss": "0.00%"},
                {"ip": "172.64.229.122", "speed": "5.50mb/s", "ping": "80.00ms", "loss": "0.00%"},  # 低于 10，淘汰
                {"ip": "127.0.0.1", "speed": "20.00mb/s", "ping": "10.00ms", "loss": "0.00%"},      # 私网，淘汰
                {"ip": "invalid-ip", "speed": "30.00mb/s", "ping": "10.00ms", "loss": "0.00%"},     # 非法 IP，淘汰
            ]
        },
        "cucc": {
            "info": [
                {"ip": "104.17.141.228", "speed": "21.57mb/s", "ping": "164.40ms", "loss": "0.00%"},
                {"ip": "172.64.229.121", "speed": "15.00mb/s", "ping": "52.00ms", "loss": "0.00%"},  # 重复 IP，跳过
            ]
        }
    }

    nodes = crawler.extract_raw_nodes(mock_data, min_speed=10.0)
    assert len(nodes) == 2
    ips = [n.ip for n in nodes]
    assert "172.64.229.121" in ips
    assert "104.17.141.228" in ips
    assert "172.64.229.122" not in ips
    assert "127.0.0.1" not in ips


def test_crawl_and_format_sorted_descending():
    """测试完整采集流程与结果按速度倒序排列"""
    crawler = UOUINCrawler()

    mock_api_data = {
        "ctcc": {
            "info": [
                {"ip": "1.1.1.1", "speed": "12.00mb/s", "ping": "60.00ms"},
                {"ip": "2.2.2.2", "speed": "50.00mb/s", "ping": "40.00ms"},
                {"ip": "3.3.3.3", "speed": "25.00mb/s", "ping": "50.00ms"},
            ]
        }
    }

    mock_geo_map = {
        "1.1.1.1": GeoInfo(country_code="US", country="美国", city="洛杉矶"),
        "2.2.2.2": GeoInfo(country_code="US", country="美国", city="旧金山"),
        "3.3.3.3": GeoInfo(country_code="JP", country="日本", city="东京"),
    }

    with patch.object(crawler, "fetch_api_data", return_value=mock_api_data):
        with patch.object(crawler.geo_resolver, "resolve_all", return_value=mock_geo_map):
            results = crawler.crawl_and_format(min_speed=10.0)

            assert len(results) == 3
            # 验证速度倒序: 50.00 > 25.00 > 12.00
            speeds = [item[0] for item in results]
            assert speeds == [50.0, 25.0, 12.0]

            lines = [item[1] for item in results]
            assert lines[0] == "2.2.2.2:443#麒麟优选-电信-US-美国 旧金山-40.00ms-50.00mb/s"
            assert lines[1] == "3.3.3.3:443#麒麟优选-电信-JP-日本 东京-50.00ms-25.00mb/s"
            assert lines[2] == "1.1.1.1:443#麒麟优选-电信-US-美国 洛杉矶-60.00ms-12.00mb/s"
