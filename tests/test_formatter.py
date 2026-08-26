"""
节点格式化引擎单元测试
全面覆盖域名、IP、端口省略/保留、前缀备注填充、去重等业务规则。
"""

import pytest
from crawler.formatter import is_valid_ip, format_single_node, format_node_list


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


def test_format_node_list_and_deduplication():
    """
    测试批量格式化与去重逻辑
    """
    items = [
        {"ip": "www.shopify.com", "pingPort": 443, "providerUrl": None},
        {"ip": "dnew.cc", "pingPort": 443, "providerUrl": "yong"},
        {"ip": "www.shopify.com", "pingPort": 443, "providerUrl": None},  # 重复项
        {"ip": "104.21.20.210", "pingPort": 443, "providerUrl": None}
    ]
    formatted = format_node_list(items, deduplicate=True)
    lines = formatted.splitlines()
    assert len(lines) == 3
    assert lines[0] == "www.shopify.com#vps789-www.shopify.com"
    assert lines[1] == "dnew.cc#vps789-yong"
    assert lines[2] == "104.21.20.210:443#vps789-104.21.20.210"
