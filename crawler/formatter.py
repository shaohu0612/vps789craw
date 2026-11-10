"""
VPS789 节点数据清洗与格式化引擎
支持 CNAME 域名评分筛选 (>=80)、按下载速度倒序排列、地理位置识别 (国家/城市)、延迟与速度规范化。
最终输出成果标准格式: IP:端口#vps789-国家简码-国家 城市-延迟-速度 (无法确认城市时确认国家即可)
"""

import ipaddress
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from crawler.geo import (
    GeoInfo,
    GeoResolver,
    batch_resolve_domains,
)

logger = logging.getLogger(__name__)


@dataclass
class ParsedNode:
    """
    清洗解析后的节点中间模型
    """
    host: str
    port: int
    is_ip: bool
    is_ipv6: bool
    score: Optional[float]
    latency: float
    speed: float
    latency_str: str
    speed_str: str
    raw_item: Dict[str, Any]


def is_valid_ip(host: str) -> bool:
    """
    判断给定主机字符串是否为合法的 IPv4 或 IPv6 地址。
    """
    if not host or not isinstance(host, str):
        return False
    clean_host = host.strip("[] \t\r\n")
    try:
        ipaddress.ip_address(clean_host)
        return True
    except ValueError:
        return False


def calculate_three_network_metrics(item: Dict[str, Any]) -> Tuple[float, float]:
    """
    计算节点在电信、移动、联通三网下的平均延迟(ms)与平均丢包率(%)。
    若三网独立字段缺失，回退到整体综合指标 (avgLatency, avgPkgLostRate)。
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
    判断节点是否满足三网平均延迟与平均丢包率质量红线。
    """
    avg_latency, avg_loss_rate = calculate_three_network_metrics(item)

    if max_latency is not None and avg_latency > max_latency:
        return False

    if max_loss_rate is not None and avg_loss_rate > max_loss_rate:
        return False

    return True


def parse_speed_value(item: Dict[str, Any]) -> Tuple[float, str]:
    """
    提取下载速度数值 (单位 mb/s) 与格式化展示字符串。
    VPS789 接口中 downloadSpeed 常见值为字符串（如 '14200' 代表 14.20 mb/s）。
    若无测速数据，则默认返回 (0.0, '0.00mb/s')。
    """
    raw_val = item.get("downloadSpeed")
    if raw_val is None:
        return 0.0, "0.00mb/s"

    try:
        val_str = str(raw_val).strip()
        num_match = re.search(r"(\d+(?:\.\d+)?)", val_str)
        if not num_match:
            return 0.0, "0.00mb/s"

        num = float(num_match.group(1))
        # 若数值大于 1000 (例如 14200)，将其折算为 mb/s (除以 1000)
        if num >= 1000:
            speed_mb = num / 1000.0
        else:
            speed_mb = num

        return round(speed_mb, 2), f"{speed_mb:.2f}mb/s"
    except Exception:
        return 0.0, "0.00mb/s"


def parse_latency_value(item: Dict[str, Any]) -> Tuple[float, str]:
    """
    提取平均延迟数值 (ms) 与格式化展示字符串。
    优先计算三网平均延迟，若为 0 则使用 avgLatency。
    """
    avg_lat, _ = calculate_three_network_metrics(item)
    if avg_lat <= 0:
        raw_lat = item.get("avgLatency")
        try:
            avg_lat = float(raw_lat) if raw_lat is not None else 0.0
        except (ValueError, TypeError):
            avg_lat = 0.0

    return round(avg_lat, 2), f"{round(avg_lat):.0f}ms"


def parse_single_item(item: Dict[str, Any]) -> Optional[ParsedNode]:
    """
    解析单条原始字典数据为 ParsedNode
    """
    raw_host = str(item.get("ip", "")).strip()
    if not raw_host:
        return None

    # 提取端口，页面无端口的默认为 443
    raw_port = item.get("pingPort")
    try:
        port = int(raw_port) if raw_port is not None else 443
        if port <= 0 or port > 65535:
            port = 443
    except (ValueError, TypeError):
        port = 443

    clean_host = raw_host.strip("[]")
    is_ip = is_valid_ip(clean_host)
    is_ipv6 = False
    if is_ip:
        try:
            is_ipv6 = ipaddress.ip_address(clean_host).version == 6
        except ValueError:
            is_ipv6 = False

    # 提取评分 (优选 CNAME 域名评分)
    score_raw = item.get("cfCnamescore")
    score: Optional[float] = None
    if score_raw is not None:
        try:
            score = float(score_raw)
        except (ValueError, TypeError):
            score = None

    speed_val, speed_str = parse_speed_value(item)
    lat_val, lat_str = parse_latency_value(item)

    return ParsedNode(
        host=clean_host,
        port=port,
        is_ip=is_ip,
        is_ipv6=is_ipv6,
        score=score,
        latency=lat_val,
        speed=speed_val,
        latency_str=lat_str,
        speed_str=speed_str,
        raw_item=item
    )


def format_node_line(
    node: ParsedNode,
    geo: Optional[GeoInfo] = None,
    prefix: str = "vps789-"
) -> str:
    """
    格式化单行输出:
    IP:端口#vps789-国家简码-国家 城市-延迟-速度
    若城市无法确认，输出: IP:端口#vps789-国家简码-国家-延迟-速度
    """
    # 格式化主机与端口 (页面无端口默认 443，IPv6 使用 [IPv6]:端口)
    if node.is_ipv6:
        host_port = f"[{node.host}]:{node.port}"
    else:
        host_port = f"{node.host}:{node.port}"

    clean_prefix = prefix.strip()
    if clean_prefix and not clean_prefix.endswith("-"):
        clean_prefix = f"{clean_prefix}-"

    # geo.geo_text 自动处理城市未知时仅输出 '国家简码-国家'
    geo_desc = geo.geo_text if geo else "US-美国"

    return f"{host_port}#{clean_prefix}{geo_desc}-{node.latency_str}-{node.speed_str}"


def format_single_node(
    item: Dict[str, Any],
    prefix: str = "vps789-",
    geo: Optional[GeoInfo] = None
) -> Optional[str]:
    """
    格式化单条节点数据 (兼顾向后兼容与直接调用)
    """
    node = parse_single_item(item)
    if not node:
        return None
    return format_node_line(node, geo, prefix=prefix)


def format_vps789_list(
    items: List[Dict[str, Any]],
    crawl_type: str = "domain",
    prefix: str = "vps789-",
    min_score: Optional[float] = 80.0,
    max_latency: Optional[float] = 300.0,
    max_loss_rate: Optional[float] = 10.0,
    geo_resolver: Optional[GeoResolver] = None
) -> str:
    """
    VPS789 节点全流程批量格式化引擎。
    规则:
    1. 优选 CNAME 域名 (domain):
       - 筛选评分 >= min_score (默认 80)
       - 质量指标过滤 (平均延迟 <= max_latency, 丢包率 <= max_loss_rate)
       - 并发 DNS 解析域名获取 IP，进而查询 Geo 地理信息 (无法确认城市则确认国家)
       - 最终按照下载速度倒序排列 (从高到低)
    2. 优选 IP (ip):
       - 质量指标过滤 (若配置)
       - 批量查询 Geo 地理信息 (国家 城市)
       - 延迟升序或优选顺序排列
    """
    if not items:
        return ""

    resolver = geo_resolver or GeoResolver()

    # 1. 初步解析与过滤
    parsed_nodes: List[ParsedNode] = []
    seen_hosts = set()

    for it in items:
        node = parse_single_item(it)
        if not node:
            continue

        # CNAME 优选域名模式: 筛选评分 >= min_score
        if crawl_type == "domain":
            if min_score is not None:
                if node.score is None or node.score < min_score:
                    continue

        # 网络质量过滤 (三网平均延迟与丢包率)
        if max_latency is not None or max_loss_rate is not None:
            if not is_node_qualified(node.raw_item, max_latency=max_latency, max_loss_rate=max_loss_rate):
                continue

        # 主机去重
        if node.host in seen_hosts:
            continue
        seen_hosts.add(node.host)
        parsed_nodes.append(node)

    if not parsed_nodes:
        return ""

    # 2. 地理位置解析
    # 若为域名，先解析为 IP，再解析 Geo
    host_to_ip: Dict[str, str] = {}
    ips_to_query: List[str] = []

    domains_to_resolve: List[str] = [n.host for n in parsed_nodes if not n.is_ip]
    if domains_to_resolve:
        logger.info(f"正在并发解析 {len(domains_to_resolve)} 个优选域名的 DNS A 记录...")
        resolved_dns = batch_resolve_domains(domains_to_resolve)
        for dom, ip in resolved_dns.items():
            if ip:
                host_to_ip[dom] = ip
                ips_to_query.append(ip)

    for n in parsed_nodes:
        if n.is_ip:
            host_to_ip[n.host] = n.host
            ips_to_query.append(n.host)

    # 批量解析 IP 地理信息
    geo_map: Dict[str, GeoInfo] = {}
    if ips_to_query:
        logger.info(f"正在批量解析 {len(ips_to_query)} 个节点的地理位置信息...")
        geo_map = resolver.resolve_all(ips_to_query)

    # 3. 组装输出文本并排序
    # 格式化元组: (sort_key, line_str)
    formatted_entries: List[Tuple[Tuple[float, float], str]] = []

    for node in parsed_nodes:
        mapped_ip = host_to_ip.get(node.host)
        geo = geo_map.get(mapped_ip) if mapped_ip else None
        if not geo:
            # 兜底：若未解析到 IP 或 Geo，无法确认城市时确认国家即可
            geo = GeoInfo(country_code="US", country="美国", city="")

        line = format_node_line(node, geo, prefix=prefix)

        # 排序键规则:
        # domain 模式: 按照下载速度倒序 (从大到小, -speed)，同速度按延迟升序 (有效延迟优先)
        # ip 模式: 按照延迟升序 (有效延迟 > 0 优先)，无效延迟排在最后
        effective_latency = node.latency if node.latency > 0 else 9999.0
        if crawl_type == "domain":
            sort_key = (-node.speed, effective_latency)
        else:
            sort_key = (effective_latency, -node.speed)

        formatted_entries.append((sort_key, line))

    # 执行排序
    formatted_entries.sort(key=lambda x: x[0])

    lines = [entry[1] for entry in formatted_entries]
    return "\n".join(lines)


# 保持与旧接口的向下兼容
def format_node_list(
    items: List[Dict[str, Any]],
    prefix: str = "vps789-",
    deduplicate: bool = True,
    max_latency: Optional[float] = None,
    max_loss_rate: Optional[float] = None,
    crawl_type: str = "domain",
    min_score: Optional[float] = 80.0
) -> str:
    """向下兼容的批量格式化入口"""
    return format_vps789_list(
        items=items,
        crawl_type=crawl_type,
        prefix=prefix,
        min_score=min_score if crawl_type == "domain" else None,
        max_latency=max_latency,
        max_loss_rate=max_loss_rate
    )
