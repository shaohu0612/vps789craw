"""
VPS789 优选域名转 IP 业务编排与格式化引擎 (DomainsToIPEngine)
组合底层的 DNSResolver (DNS 解析引擎) 与 GeoResolver (地理位置增强引擎)，
实现从优选域名到底层 Anycast 优选 IP 的解析、清洗、去重择优、地理位置元数据增强及速度倒序导出。
"""

import ipaddress
import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from crawler.dns_resolver import DNSResolver
from crawler.geo import GeoInfo, GeoResolver

logger = logging.getLogger(__name__)


@dataclass
class DomainSourceNode:
    """输入的优选域名节点数据"""
    domain: str
    port: int
    latency: int
    speed: float
    raw_line: str


@dataclass
class Domains2IPNode:
    """域名解析后的优选 IP 节点成果数据"""
    ip: str
    port: int
    latency: int
    speed: float
    is_ipv6: bool
    geo: Optional[GeoInfo] = None

    @property
    def formatted_line(self) -> str:
        """
        按照全局规范格式化输出:
        IP:端口#vps789-国家简码-国家 城市-延迟-速度
        IPv4 为 ip:443，IPv6 为 [ip]:443
        示例: 172.64.156.130:443#vps789-CA-加拿大 多伦多-118ms-14.50mb/s
        """
        ip_repr = f"[{self.ip}]" if self.is_ipv6 else self.ip
        geo_str = self.geo.geo_text if self.geo else "US-美国"
        return f"{ip_repr}:{self.port}#vps789-{geo_str}-{self.latency}ms-{self.speed:.2f}mb/s"


class DomainsToIPEngine:
    """
    优选域名转 IP 业务编排器
    解耦组合 DNSResolver 和 GeoResolver
    """

    def __init__(
        self,
        dns_resolver: Optional[DNSResolver] = None,
        geo_resolver: Optional[GeoResolver] = None
    ):
        self.dns_resolver = dns_resolver or DNSResolver()
        self.geo_resolver = geo_resolver or GeoResolver()

    @staticmethod
    def parse_domain_line(line: str) -> Optional[DomainSourceNode]:
        """
        从单行优选域名文本中解析出域名、端口、延迟与速度
        支持格式如: 11.cf.3666888.xyz:443#vps789-CA-加拿大 多伦多-118ms-14.50mb/s
        """
        line = line.strip()
        if not line or line.startswith("//"):
            return None

        # 匹配 域名:端口#备注
        match = re.match(
            r"^([a-zA-Z0-9][-a-zA-Z0-9.]*[a-zA-Z0-9]):?(\d+)?#(.*)$",
            line
        )
        if not match:
            return None

        domain = match.group(1).strip()
        port = int(match.group(2)) if match.group(2) else 443
        remark = match.group(3).strip()

        latency = 0
        speed = 0.0

        lat_match = re.search(r"(\d+)ms", remark)
        if lat_match:
            latency = int(lat_match.group(1))

        speed_match = re.search(r"(\d+(?:\.\d+)?)mb/s", remark, re.IGNORECASE)
        if speed_match:
            speed = float(speed_match.group(1))

        return DomainSourceNode(
            domain=domain,
            port=port,
            latency=latency,
            speed=speed,
            raw_line=line
        )

    def convert_domain_lines_to_nodes(
        self,
        domain_lines: List[str],
        resolve_v6: bool = True
    ) -> List[Domains2IPNode]:
        """
        核心编排逻辑：
        1. 解析域名列表 -> 2. 并发 DNS 解析 -> 3. IP 择优去重 -> 4. 批量 Geo 增强 -> 5. 速度倒序排序
        """
        # 1. 解析输入的每行优选域名
        source_nodes: List[DomainSourceNode] = []
        for line in domain_lines:
            node = self.parse_domain_line(line)
            if node:
                source_nodes.append(node)

        if not source_nodes:
            logger.warning("未提供或未解析到任何合法的优选域名行")
            return []

        # 2. 调度 DNSResolver 执行批量并发解析
        domains = [item.domain for item in source_nodes]
        domain_ip_map = self.dns_resolver.resolve_batch(domains, resolve_v6=resolve_v6)

        # 3. 将解析出的 IP 进行去重与指标择优合并
        # 若同一个 IP 被多个域名解析出来，优先保留测速更快、延迟更优的记录
        domain_lookup: Dict[str, DomainSourceNode] = {item.domain: item for item in source_nodes}
        ip_node_map: Dict[str, Domains2IPNode] = {}

        for domain, ips in domain_ip_map.items():
            source_item = domain_lookup.get(domain)
            if not source_item:
                continue

            for ip in ips:
                try:
                    ip_obj = ipaddress.ip_address(ip)
                    is_v6 = (ip_obj.version == 6)
                except ValueError:
                    continue

                if ip not in ip_node_map:
                    ip_node_map[ip] = Domains2IPNode(
                        ip=ip,
                        port=source_item.port,
                        latency=source_item.latency,
                        speed=source_item.speed,
                        is_ipv6=is_v6
                    )
                else:
                    curr = ip_node_map[ip]
                    # 择优保留逻辑：速度更高优先；同速度下延迟更低优先
                    if source_item.speed > curr.speed or (
                        abs(source_item.speed - curr.speed) < 1e-6 and source_item.latency < curr.latency
                    ):
                        curr.speed = source_item.speed
                        curr.latency = source_item.latency
                        curr.port = source_item.port

        unique_ips = list(ip_node_map.keys())
        if not unique_ips:
            logger.warning("所有优选域名均未解析出有效的公网 IP 地址")
            return []

        logger.info(f"===> 域名解析共获得 {len(unique_ips)} 个独立公网 IP，开始批量地理位置识别与中文化增强...")

        # 4. 调度 GeoResolver 进行批量地理位置增强
        geo_dict = self.geo_resolver.resolve_all(unique_ips)
        for ip, node in ip_node_map.items():
            node.geo = geo_dict.get(ip)

        # 5. 按照下载速度倒序排列（从高到低），同速度下按延迟升序微调
        sorted_nodes = sorted(
            ip_node_map.values(),
            key=lambda x: (-x.speed, x.latency if x.latency > 0 else 99999)
        )

        return sorted_nodes

    def process_file(
        self,
        domains_file_path: str,
        output_file_path: str,
        resolve_v6: bool = True
    ) -> int:
        """
        处理优选域名文件并输出到目标文件 (vps789-domains2ip)
        """
        if not os.path.exists(domains_file_path):
            logger.error(f"源优选域名文件不存在: {domains_file_path}")
            return 0

        with open(domains_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        nodes = self.convert_domain_lines_to_nodes(lines, resolve_v6=resolve_v6)
        if not nodes:
            logger.warning("域名解析完成但无有效输出节点")
            return 0

        formatted_content = "\n".join(node.formatted_line for node in nodes) + "\n"

        out_dir = os.path.dirname(os.path.abspath(output_file_path))
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        with open(output_file_path, "w", encoding="utf-8") as f:
            f.write(formatted_content)

        logger.info(f"🎉 成功导出域名解析 IP 成果物: {output_file_path} (共 {len(nodes)} 条)")
        return len(nodes)


def run_domains2ip(
    domains_file: str = "vps789-domains",
    output_file: str = "vps789-domains2ip",
    resolve_v6: bool = True
) -> int:
    """
    运行优选域名转 IP 的便捷入口函数
    """
    engine = DomainsToIPEngine()
    return engine.process_file(
        domains_file_path=domains_file,
        output_file_path=output_file,
        resolve_v6=resolve_v6
    )
