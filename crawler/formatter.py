"""
节点数据清洗与格式化引擎
依据业务规则将 VPS789 采集到的优选节点数据转换为标准订阅文本格式。
"""

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class FormattedNode:
    """
    格式化后的节点数据结构
    """
    raw_ip: str
    port: int
    raw_remarks: Optional[str]
    is_ip: bool
    formatted_line: str


def is_valid_ip(host: str) -> bool:
    """
    判断给定主机字符串是否为合法的 IPv4 或 IPv6 地址。

    :param host: 主机名或 IP 字符串
    :return: 若为 IP 地址返回 True，否则（如普通域名）返回 False
    """
    if not host or not isinstance(host, str):
        return False
    clean_host = host.strip()
    try:
        ipaddress.ip_address(clean_host)
        return True
    except ValueError:
        return False


def format_single_node(item: Dict[str, Any], suffix: str = "vps789") -> Optional[str]:
    """
    格式化单条 VPS789 节点数据为: CF优选IP[:端口]#备注-后缀

    规则:
    1. CF优选IP取自 item['ip']。
    2. 若 CF优选IP 为 IP 地址，则 :端口 不可省略（例如 104.21.20.210:443）。
    3. 若 CF优选IP 为正常域名：
       - 若端口为 443，则 :端口 省略（例如 cdn.example.com）。
       - 若端口不为 443，则 :端口 保留（例如 cdn.example.com:8443）。
    4. 备注取自 item['providerUrl']，若为空或纯空白，则复用 CF优选IP 的内容。
    5. 后缀默认为 vps789。

    :param item: 节点原始字典数据
    :param suffix: 备注后缀，默认为 "vps789"
    :return: 格式化后的字符串行，若数据不合法则返回 None
    """
    raw_ip = str(item.get("ip", "")).strip()
    if not raw_ip:
        return None

    # 解析端口，默认 443
    raw_port = item.get("pingPort")
    try:
        port = int(raw_port) if raw_port is not None else 443
        if port <= 0 or port > 65535:
            port = 443
    except (ValueError, TypeError):
        port = 443

    # 判断是否为 IP 地址
    is_ip = is_valid_ip(raw_ip)

    # 格式化主机与端口部分
    if is_ip:
        # IP 地址：:端口 绝不可省略
        host_port_str = f"{raw_ip}:{port}"
    else:
        # 正常域名：端口为 443 时省略，否则保留
        if port == 443:
            host_port_str = raw_ip
        else:
            host_port_str = f"{raw_ip}:{port}"

    # 解析备注部分 (网页端“备注”列对应字段为 providerUrl)
    provider_url = item.get("providerUrl")
    if provider_url is not None and str(provider_url).strip():
        # 清理可能存在的换行与前后空格
        clean_remarks = re.sub(r"[\r\n]+", " ", str(provider_url)).strip()
    else:
        # 备注为空时，复用域名/IP列内容
        clean_remarks = raw_ip

    clean_suffix = suffix.strip() if suffix else "vps789"
    formatted_line = f"{host_port_str}#{clean_remarks}-{clean_suffix}"
    return formatted_line


def format_node_list(items: List[Dict[str, Any]], suffix: str = "vps789", deduplicate: bool = True) -> str:
    """
    批量格式化节点列表为多行文本。

    :param items: 原始节点列表
    :param suffix: 节点后缀
    :param deduplicate: 是否对生成的行进行去重，默认 True 保留首个出现的记录
    :return: 换行符连接的格式化文本
    """
    lines: List[str] = []
    seen = set()

    for item in items:
        line = format_single_node(item, suffix=suffix)
        if not line:
            continue
        if deduplicate:
            if line in seen:
                continue
            seen.add(line)
        lines.append(line)

    return "\n".join(lines)
