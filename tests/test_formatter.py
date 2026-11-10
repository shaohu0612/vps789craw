"""
节点格式化引擎单元测试
覆盖 IP/域名格式化 (IP:端口#vps789-国家简码-国家 城市-延迟-速度)、CNAME 评分筛选 (>=80)、速度倒序排序、质量过滤等业务规则。
"""

import pytest
from crawler.formatter import (
    is_valid_ip,
    parse_speed_value,
    parse_latency_value,
    parse_single_item,
    format_node_line,
    format_single_node,
    format_vps789_list,
    calculate_three_network_metrics,
    is_node_qualified,
)
from crawler.geo import GeoInfo


def test_is_valid_ip():
    """测试 IP 判定"""
    assert is_valid_ip("1.1.1.1") is True
    assert is_valid_ip("104.21.20.210") is True
    assert is_valid_ip("172.67.212.221") is True
    assert is_valid_ip("2606:4700:3037::ac43:d4dd") is True

    assert is_valid_ip("www.shopify.com") is False
    assert is_valid_ip("cfsaas.080112.xyz") is False
    assert is_valid_ip("") is False
    assert is_valid_ip(None) is False


def test_parse_speed_value():
    """测试下载速度转换 (例如 14200 -> 14.20mb/s)"""
    # 字符串整千折算
    val1, str1 = parse_speed_value({"downloadSpeed": "14200"})
    assert val1 == 14.20
    assert str1 == "14.20mb/s"

    # 数值整千折算
    val2, str2 = parse_speed_value({"downloadSpeed": 12300})
    assert val2 == 12.30
    assert str2 == "12.30mb/s"

    # 小于 1000 的正常数值
    val3, str3 = parse_speed_value({"downloadSpeed": "25.5"})
    assert val3 == 25.5
    assert str3 == "25.50mb/s"

    # 缺失或非法值 -> 0.00mb/s
    val4, str4 = parse_speed_value({})
    assert val4 == 0.0
    assert str4 == "0.00mb/s"


def test_parse_latency_value():
    """测试延迟解析"""
    # 三网平均延迟
    item1 = {
        "dxLatencyAvg": 100,
        "ydLatencyAvg": 150,
        "ltLatencyAvg": 200,
    }
    val1, str1 = parse_latency_value(item1)
    assert val1 == 150.0
    assert str1 == "150ms"

    # 综合 avgLatency 回退
    item2 = {"avgLatency": 185}
    val2, str2 = parse_latency_value(item2)
    assert val2 == 185.0
    assert str2 == "185ms"


def test_format_node_line_with_city():
    """测试带有完整城市信息的格式化行"""
    item = {
        "ip": "cfsaas.080112.xyz",
        "pingPort": 443,
        "avgLatency": 193,
        "downloadSpeed": "14200",
        "cfCnamescore": 98
    }
    node = parse_single_item(item)
    assert node is not None

    geo = GeoInfo(country_code="CA", country="加拿大", city="多伦多")
    line = format_node_line(node, geo, prefix="vps789-")
    assert line == "cfsaas.080112.xyz:443#vps789-CA-加拿大 多伦多-193ms-14.20mb/s"


def test_format_node_line_without_city():
    """测试无法确认城市时仅确认国家的格式化行"""
    item = {
        "ip": "test.example.com",
        "pingPort": 443,
        "avgLatency": 150,
        "downloadSpeed": "12000"
    }
    node = parse_single_item(item)
    assert node is not None

    # 城市为空或未知
    geo = GeoInfo(country_code="US", country="美国", city="")
    line = format_node_line(node, geo, prefix="vps789-")
    assert line == "test.example.com:443#vps789-US-美国-150ms-12.00mb/s"

    geo2 = GeoInfo(country_code="US", country="美国", city="未知城市")
    line2 = format_node_line(node, geo2, prefix="vps789-")
    assert line2 == "test.example.com:443#vps789-US-美国-150ms-12.00mb/s"


def test_format_node_line_ipv6():
    """测试 IPv6 格式化包含方括号端口"""
    item = {
        "ip": "2606:4700:3037::ac43:d4dd",
        "pingPort": 443,
        "avgLatency": 120
    }
    node = parse_single_item(item)
    assert node is not None
    assert node.is_ipv6 is True

    geo = GeoInfo(country_code="GB", country="英国", city="伦敦")
    line = format_node_line(node, geo, prefix="vps789-")
    assert line == "[2606:4700:3037::ac43:d4dd]:443#vps789-GB-英国 伦敦-120ms-0.00mb/s"


def test_format_vps789_list_domain_score_filter_and_speed_sort(monkeypatch):
    """测试 CNAME 域名评分 >= 80 过滤与按下载速度倒序排列"""
    items = [
        # 低于 80 分 -> 应被剔除
        {"ip": "low-score.com", "pingPort": 443, "cfCnamescore": 75, "downloadSpeed": "16000", "avgLatency": 100},
        # 80 分，速度 12.00mb/s
        {"ip": "score-80.com", "pingPort": 443, "cfCnamescore": 80, "downloadSpeed": "12000", "avgLatency": 110},
        # 98 分，速度 14.50mb/s
        {"ip": "score-98.com", "pingPort": 443, "cfCnamescore": 98, "downloadSpeed": "14500", "avgLatency": 120},
        # 90 分，速度 13.00mb/s
        {"ip": "score-90.com", "pingPort": 443, "cfCnamescore": 90, "downloadSpeed": "13000", "avgLatency": 115},
    ]

    # Mock DNS 与 Geo 避免外部网络调用
    monkeypatch.setattr(
        "crawler.formatter.batch_resolve_domains",
        lambda domains: {d: "1.1.1.1" for d in domains}
    )

    class MockResolver:
        def resolve_all(self, ips):
            return {"1.1.1.1": GeoInfo(country_code="US", country="美国", city="旧金山")}

    result = format_vps789_list(
        items,
        crawl_type="domain",
        min_score=80.0,
        geo_resolver=MockResolver()
    )
    lines = result.splitlines()

    # low-score.com 应被过滤掉，保留 3 条
    assert len(lines) == 3
    assert "low-score.com" not in result

    # 按照下载速度倒序 (14.50 -> 13.00 -> 12.00)
    assert "score-98.com:443#vps789-US-美国 旧金山-120ms-14.50mb/s" == lines[0]
    assert "score-90.com:443#vps789-US-美国 旧金山-115ms-13.00mb/s" == lines[1]
    assert "score-80.com:443#vps789-US-美国 旧金山-110ms-12.00mb/s" == lines[2]


def test_quality_metrics_filtering():
    """测试网络质量过滤 (延迟 > 300ms 或 丢包率 > 10% 过滤)"""
    good_item = {"dxLatencyAvg": 150, "ydLatencyAvg": 150, "ltLatencyAvg": 150, "dxPkgLostRateAvg": 1, "ydPkgLostRateAvg": 1, "ltPkgLostRateAvg": 1}
    bad_lat = {"dxLatencyAvg": 350, "ydLatencyAvg": 350, "ltLatencyAvg": 350, "dxPkgLostRateAvg": 1, "ydPkgLostRateAvg": 1, "ltPkgLostRateAvg": 1}
    bad_loss = {"dxLatencyAvg": 150, "ydLatencyAvg": 150, "ltLatencyAvg": 150, "dxPkgLostRateAvg": 15, "ydPkgLostRateAvg": 15, "ltPkgLostRateAvg": 15}

    assert is_node_qualified(good_item) is True
    assert is_node_qualified(bad_lat) is False
    assert is_node_qualified(bad_loss) is False
