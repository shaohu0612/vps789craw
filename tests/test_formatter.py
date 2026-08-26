"""
节点格式化引擎单元测试
全面覆盖域名、IP、端口省略/保留、前缀备注填充、去重等业务规则。
"""

import pytest
from crawler.formatter import (
    is_valid_ip,
    format_single_node,
    format_node_list,
    calculate_three_network_metrics,
    is_node_qualified
)


def test_is_valid_ip():
    """
    测试 IP 判断逻辑
    """
    assert is_valid_ip("1.1.1.1") is True
    assert is_valid_ip("104.21.20.210") is True
    assert is_valid_ip("172.67.212.221") is True
    assert is_valid_ip("2606:4700:3037::ac43:d4dd") is True

    assert is_valid_ip("www.shopify.com") is False
    assert is_valid_ip("cdn.204910.best") is False
    assert is_valid_ip("dnew.cc") is False
    assert is_valid_ip("") is False
    assert is_valid_ip(None) is False


def test_format_domain_with_port_443_and_remarks():
    """
    测试正常域名、端口 443、有备注的情况 -> :443 省略，前缀为 vps789-
    """
    item = {
        "ip": "dnew.cc",
        "pingPort": 443,
        "providerUrl": "yong"
    }
    result = format_single_node(item)
    assert result == "dnew.cc#vps789-yong"


def test_format_domain_with_port_443_and_empty_remarks():
    """
    测试正常域名、端口 443、无备注的情况 -> :443 省略，备注复用域名
    """
    item = {
        "ip": "www.shopify.com",
        "pingPort": 443,
        "providerUrl": None
    }
    result = format_single_node(item)
    assert result == "www.shopify.com#vps789-www.shopify.com"


def test_format_domain_with_non_443_port():
    """
    测试正常域名、非 443 端口的情况 -> 必须保留 :端口
    """
    item = {
        "ip": "speed.cloudflare.com",
        "pingPort": 8443,
        "providerUrl": "官方测速"
    }
    result = format_single_node(item)
    assert result == "speed.cloudflare.com:8443#vps789-官方测速"


def test_format_ipv4_with_port_443():
    """
    测试 IPv4 地址、端口 443 -> :443 绝不可省略，前缀为 vps789-
    """
    item = {
        "ip": "104.21.20.210",
        "pingPort": 443,
        "providerUrl": None
    }
    result = format_single_node(item)
    assert result == "104.21.20.210:443#vps789-104.21.20.210"


def test_format_ipv4_with_non_443_port_and_remarks():
    """
    测试 IPv4 地址、非 443 端口、有备注
    """
    item = {
        "ip": "172.67.212.221",
        "pingPort": 2053,
        "providerUrl": "高防节点"
    }
    result = format_single_node(item)
    assert result == "172.67.212.221:2053#vps789-高防节点"


def test_format_ipv6_node():
    """
    测试 IPv6 地址节点格式化
    """
    item = {
        "ip": "2606:4700:3037::ac43:d4dd",
        "pingPort": 443,
        "providerUrl": ""
    }
    result = format_single_node(item)
    assert result == "2606:4700:3037::ac43:d4dd:443#vps789-2606:4700:3037::ac43:d4dd"


def test_calculate_three_network_metrics():
    """
    测试三网平均延迟与丢包率计算
    """
    # 完整三网数据
    item1 = {
        "dxLatencyAvg": 100,
        "ydLatencyAvg": 200,
        "ltLatencyAvg": 300,
        "dxPkgLostRateAvg": 1.0,
        "ydPkgLostRateAvg": 2.0,
        "ltPkgLostRateAvg": 3.0,
    }
    lat, loss = calculate_three_network_metrics(item1)
    assert pytest.approx(lat, 0.01) == 200.0
    assert pytest.approx(loss, 0.01) == 2.0

    # 部分字段缺失回退到有效字段平均
    item2 = {
        "dxLatencyAvg": 100,
        "ydLatencyAvg": None,
        "ltLatencyAvg": 200,
        "dxPkgLostRateAvg": 5.0,
        "ydPkgLostRateAvg": None,
        "ltPkgLostRateAvg": None,
    }
    lat, loss = calculate_three_network_metrics(item2)
    assert pytest.approx(lat, 0.01) == 150.0
    assert pytest.approx(loss, 0.01) == 5.0

    # 全部独立字段缺失回退到综合指标
    item3 = {
        "avgLatency": 180,
        "avgPkgLostRate": 4.5,
    }
    lat, loss = calculate_three_network_metrics(item3)
    assert pytest.approx(lat, 0.01) == 180.0
    assert pytest.approx(loss, 0.01) == 4.5


def test_is_node_qualified():
    """
    测试节点质量判断逻辑 (延迟 <= 300ms 且 丢包率 <= 10%)
    """
    # 正常合格节点 (延迟 150ms, 丢包率 2%)
    qualified_item = {
        "dxLatencyAvg": 100,
        "ydLatencyAvg": 150,
        "ltLatencyAvg": 200,
        "dxPkgLostRateAvg": 1.0,
        "ydPkgLostRateAvg": 2.0,
        "ltPkgLostRateAvg": 3.0,
    }
    assert is_node_qualified(qualified_item) is True

    # 边界值: 刚好 300ms 和 10% -> 合格
    boundary_item = {
        "dxLatencyAvg": 300,
        "ydLatencyAvg": 300,
        "ltLatencyAvg": 300,
        "dxPkgLostRateAvg": 10.0,
        "ydPkgLostRateAvg": 10.0,
        "ltPkgLostRateAvg": 10.0,
    }
    assert is_node_qualified(boundary_item) is True

    # 延迟超标 (>300ms)
    high_latency_item = {
        "dxLatencyAvg": 320,
        "ydLatencyAvg": 310,
        "ltLatencyAvg": 300,  # 平均 310ms > 300ms
        "dxPkgLostRateAvg": 0.0,
        "ydPkgLostRateAvg": 0.0,
        "ltPkgLostRateAvg": 0.0,
    }
    assert is_node_qualified(high_latency_item) is False

    # 丢包率超标 (>10%)
    high_loss_item = {
        "dxLatencyAvg": 120,
        "ydLatencyAvg": 110,
        "ltLatencyAvg": 130,
        "dxPkgLostRateAvg": 12.0,
        "ydPkgLostRateAvg": 15.0,
        "ltPkgLostRateAvg": 9.0,  # 平均 12% > 10%
    }
    assert is_node_qualified(high_loss_item) is False

    # 延迟与丢包率双超标
    both_bad_item = {
        "dxLatencyAvg": 350,
        "ydLatencyAvg": 350,
        "ltLatencyAvg": 350,
        "dxPkgLostRateAvg": 20.0,
        "ydPkgLostRateAvg": 20.0,
        "ltPkgLostRateAvg": 20.0,
    }
    assert is_node_qualified(both_bad_item) is False


def test_format_node_list_and_deduplication():
    """
    测试批量格式化、去重与质量过滤逻辑
    """
    items = [
        # 合格项 1
        {"ip": "www.shopify.com", "pingPort": 443, "providerUrl": None, "dxLatencyAvg": 100, "ydLatencyAvg": 100, "ltLatencyAvg": 100, "dxPkgLostRateAvg": 1, "ydPkgLostRateAvg": 1, "ltPkgLostRateAvg": 1},
        # 合格项 2
        {"ip": "dnew.cc", "pingPort": 443, "providerUrl": "yong", "dxLatencyAvg": 120, "ydLatencyAvg": 120, "ltLatencyAvg": 120, "dxPkgLostRateAvg": 2, "ydPkgLostRateAvg": 2, "ltPkgLostRateAvg": 2},
        # 重复项
        {"ip": "www.shopify.com", "pingPort": 443, "providerUrl": None, "dxLatencyAvg": 100, "ydLatencyAvg": 100, "ltLatencyAvg": 100, "dxPkgLostRateAvg": 1, "ydPkgLostRateAvg": 1, "ltPkgLostRateAvg": 1},
        # 不合格项: 延迟 350ms > 300ms
        {"ip": "bad-latency.com", "pingPort": 443, "providerUrl": "延迟高", "dxLatencyAvg": 350, "ydLatencyAvg": 350, "ltLatencyAvg": 350, "dxPkgLostRateAvg": 1, "ydPkgLostRateAvg": 1, "ltPkgLostRateAvg": 1},
        # 不合格项: 丢包 25% > 10%
        {"ip": "bad-loss.com", "pingPort": 443, "providerUrl": "丢包高", "dxLatencyAvg": 100, "ydLatencyAvg": 100, "ltLatencyAvg": 100, "dxPkgLostRateAvg": 25, "ydPkgLostRateAvg": 25, "ltPkgLostRateAvg": 25},
        # 合格 IP 项
        {"ip": "104.21.20.210", "pingPort": 443, "providerUrl": None, "dxLatencyAvg": 110, "ydLatencyAvg": 110, "ltLatencyAvg": 110, "dxPkgLostRateAvg": 0, "ydPkgLostRateAvg": 0, "ltPkgLostRateAvg": 0}
    ]

    # 启用质量过滤 (max_latency=300, max_loss_rate=10)
    formatted = format_node_list(items, deduplicate=True, max_latency=300.0, max_loss_rate=10.0)
    lines = formatted.splitlines()

    assert len(lines) == 3
    assert lines[0] == "www.shopify.com#vps789-www.shopify.com"
    assert lines[1] == "dnew.cc#vps789-yong"
    assert lines[2] == "104.21.20.210:443#vps789-104.21.20.210"
    assert "bad-latency.com" not in formatted
    assert "bad-loss.com" not in formatted

