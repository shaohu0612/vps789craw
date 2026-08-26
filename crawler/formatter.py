"""
节点数据清洗与格式化引擎
依据业务规则将 VPS789 采集到的优选节点数据转换为标准订阅文本格式，并支持按三网平均延迟和丢包率进行质量过滤。
"""

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


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


def calculate_three_network_metrics(item: Dict[str, Any]) -> Tuple[float, float]:
    """
    计算节点在电信、移动、联通三网下的平均延迟(ms)与平均丢包率(%)。

    若电信(dx)、移动(yd)、联通(lt)各独立字段存在有效数值，则计算其算术平均值；
    若独立字段均缺失或无效，则安全回退到 item 中的整体综合指标 (avgLatency, avgPkgLostRate)。

    :param item: 节点原始字典数据
    :return: (三网平均延迟_ms, 三网平均丢包率_pct)
    """
    # 提取电信、移动、联通的延迟 (ms)
    latencies: List[float] = []
    for key in ("dxLatencyAvg", "ydLatencyAvg", "ltLatencyAvg"):
        val = item.get(key)
        if val is not None:
            try:
                latencies.append(float(val))
            except (ValueError, TypeError):
                pass

    if latencies:
        avg_latency = sum(latencies) / len(latencies)
    else:
        # 回退到综合平均延迟
        raw_avg = item.get("avgLatency")
        try:
            avg_latency = float(raw_avg) if raw_avg is not None else 0.0
        except (ValueError, TypeError):
            avg_latency = 0.0

    # 提取电信、移动、联通的丢包率 (%)
    loss_rates: List[float] = []
    for key in ("dxPkgLostRateAvg", "ydPkgLostRateAvg", "ltPkgLostRateAvg"):
        val = item.get(key)
        if val is not None:
            try:
                loss_rates.append(float(val))
            except (ValueError, TypeError):
                pass

    if loss_rates:
        avg_loss_rate = sum(loss_rates) / len(loss_rates)
    else:
        # 回退到综合平均丢包率
        raw_loss = item.get("avgPkgLostRate")
        try:
            avg_loss_rate = float(raw_loss) if raw_loss is not None else 0.0
        except (ValueError, TypeError):
            avg_loss_rate = 0.0

    return avg_latency, avg_loss_rate


def is_node_qualified(
    item: Dict[str, Any],
    max_latency: Optional[float] = 300.0,
    max_loss_rate: Optional[float] = 10.0
) -> bool:
    """
    判断节点是否满足网络质量指标要求（三网平均延迟与平均丢包率）。

    规则：
    1. 若三网平均延迟 > max_latency (默认 300.0ms)，则判定为不合格 (返回 False)。
    2. 若三网平均丢包率 > max_loss_rate (默认 10.0%)，则判定为不合格 (返回 False)。
    3. 仅当均不超过门限值时返回 True。

    :param item: 节点原始字典数据
    :param max_latency: 允许的最大平均延迟 (ms)，若为 None 则不限制延迟
    :param max_loss_rate: 允许的最大平均丢包率 (%)，若为 None 则不限制丢包率
    :return: 合格返回 True，否则返回 False
    """
    avg_latency, avg_loss_rate = calculate_three_network_metrics(item)

    if max_latency is not None and avg_latency > max_latency:
        return False

    if max_loss_rate is not None and avg_loss_rate > max_loss_rate:
        return False

    return True


def format_single_node(item: Dict[str, Any], prefix: str = "vps789-") -> Optional[str]:
    """
    格式化单条 VPS789 节点数据为: CF优选IP[:端口]#前缀备注 (例如: cdn.com#vps789-备注 或 1.1.1.1:443#vps789-1.1.1.1)

    规则:
    1. CF优选IP取自 item['ip']。
    2. 若 CF优选IP 为 IP 地址，则 :端口 不可省略（例如 104.21.20.210:443）。
    3. 若 CF优选IP 为正常域名：
       - 若端口为 443，则 :端口 省略（例如 cdn.example.com）。
       - 若端口不为 443，则 :端口 保留（例如 cdn.example.com:8443）。
    4. 备注取自 item['providerUrl']，若为空或纯空白，则复用 CF优选IP 的内容。
    5. 前缀默认为 "vps789-"，插入在 # 与备注内容之间。

    :param item: 节点原始字典数据
    :param prefix: 备注前缀，默认为 "vps789-"
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

    # 处理前缀（确保前缀格式为 "vps789-"）
    if prefix:
        clean_prefix = prefix.strip()
        if not clean_prefix.endswith("-"):
            clean_prefix = f"{clean_prefix}-"
    else:
        clean_prefix = ""

    formatted_line = f"{host_port_str}#{clean_prefix}{clean_remarks}"
    return formatted_line


def format_node_list(
    items: List[Dict[str, Any]],
    prefix: str = "vps789-",
    deduplicate: bool = True,
    max_latency: Optional[float] = None,
    max_loss_rate: Optional[float] = None,
) -> str:
    """
    批量格式化节点列表为多行文本（支持质量指标过滤与去重）。

    :param items: 原始节点列表
    :param prefix: 节点备注前缀，默认 "vps789-"
    :param deduplicate: 是否对生成的行进行去重，默认 True 保留首个出现的记录
    :param max_latency: 最大允许三网平均延迟 (ms)，若指定则过滤超标节点
    :param max_loss_rate: 最大允许三网平均丢包率 (%)，若指定则过滤超标节点
    :return: 换行符连接的格式化文本
    """
    lines: List[str] = []
    seen = set()

    for item in items:
        # 质量指标过滤判断
        if max_latency is not None or max_loss_rate is not None:
            if not is_node_qualified(item, max_latency=max_latency, max_loss_rate=max_loss_rate):
                continue

        line = format_single_node(item, prefix=prefix)
        if not line:
            continue
        if deduplicate:
            if line in seen:
                continue
            seen.add(line)
        lines.append(line)

    return "\n".join(lines)
