"""
通用高性能 DNS 解析引擎模块 (DNSResolver)
专注于 RFC 1035 / RFC 3596 标准二进制 UDP DNS 报文交互、多权威 DNS 交叉解析与递归 CNAME 追踪。
纯协议与网络层实现，与上层业务数据结构完全解耦，方便全系统任意模块独立复用。
"""

import ipaddress
import logging
import random
import socket
import struct
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 精选国内与全球主流权威公共 DNS 服务器池 (复用自 E:\\myip 项目最佳实践)
DEFAULT_UDP_DNS_SERVERS: List[str] = [
    "223.5.5.5",        # 阿里 DNS 1
    "223.6.6.6",        # 阿里 DNS 2
    "119.29.29.29",     # 腾讯 DNSPod 1
    "182.254.116.116",  # 腾讯 DNSPod 2
    "114.114.114.114",  # 114 DNS 1
    "180.76.76.76",     # 百度 DNS
    "1.1.1.1",          # Cloudflare Anycast DNS 1
    "1.0.0.1",          # Cloudflare Anycast DNS 2
    "8.8.8.8",          # Google Public DNS 1
    "8.8.4.4",          # Google Public DNS 2
]


def build_dns_query_packet(domain: str, qtype: int = 1) -> bytes:
    """
    构造标准 RFC 1035 / RFC 3596 二进制 DNS 查询报文
    :param domain: 待查询的目标域名字符串
    :param qtype: 查询记录类型，1 为 A 记录 (IPv4)，28 为 AAAA 记录 (IPv6)
    :return: 序列化后的原始二进制 UDP 数据包
    """
    tid = random.randint(0, 65535)
    # Header: ID(2), Flags(2)(RD=1, 0x0100), QDCOUNT=1, ANCOUNT=0, NSCOUNT=0, ARCOUNT=0
    header = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0)

    qname_parts = []
    for part in domain.strip(".").split("."):
        encoded_part = part.encode("idna")
        qname_parts.append(bytes([len(encoded_part)]) + encoded_part)
    qname = b"".join(qname_parts) + b"\x00"

    question = qname + struct.pack("!HH", qtype, 1)  # QTYPE, QCLASS=IN(1)
    return header + question


def parse_dns_name(data: bytes, offset: int) -> Tuple[str, int]:
    """
    解析 DNS 二进制响应报文中的域名标签（支持 0xC0 偏移指针压缩解压）
    :param data: 完整的 DNS 响应原始数据
    :param offset: 当前解析游标偏移量
    :return: (解析后的完整域名字符串, 解析完成后的下一个游标偏移量)
    """
    labels: List[str] = []
    jumped = False
    original_offset = offset
    max_jumps = 20
    jumps = 0

    while True:
        if offset >= len(data):
            break
        length = data[offset]
        if length == 0:
            if not jumped:
                original_offset = offset + 1
            break
        elif (length & 0xC0) == 0xC0:
            if offset + 2 > len(data):
                break
            pointer = struct.unpack("!H", data[offset:offset + 2])[0] & 0x3FFF
            if not jumped:
                original_offset = offset + 2
                jumped = True
            offset = pointer
            jumps += 1
            if jumps > max_jumps:
                break
        else:
            offset += 1
            if offset + length > len(data):
                break
            labels.append(data[offset:offset + length].decode("ascii", errors="ignore"))
            offset += length
            if not jumped:
                original_offset = offset

    return ".".join(labels), original_offset


def query_dns_udp(
    domain: str,
    dns_server: str,
    qtype: int = 1,
    timeout: float = 1.0,
    max_cname_depth: int = 2
) -> List[str]:
    """
    通过底层 UDP Socket 向指定的单一权威 DNS 服务器发起查询并解析出 IP 结果
    具备自动递归跟随 CNAME 别名追踪底层真实 Anycast A 记录的能力。

    :param domain: 待解析域名
    :param dns_server: 目标 DNS 服务器 IP
    :param qtype: 记录类型 (1 为 A, 28 为 AAAA)
    :param timeout: 单次 Socket 超时时间（秒）
    :param max_cname_depth: 追踪 CNAME 的最大递归深度
    :return: 提取到的 IP 字符串列表
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    resolved_ips: List[str] = []
    cnames: List[str] = []

    try:
        pkt = build_dns_query_packet(domain, qtype)
        sock.sendto(pkt, (dns_server, 53))
        data, _ = sock.recvfrom(4096)

        if len(data) < 12:
            return []

        _, flags, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", data[:12])
        # 检查响应码 (RCODE) 以及是否存在应答记录
        if (flags & 0x000F) != 0 or ancount == 0:
            return []

        # 跳过 Question 区域
        offset = 12
        for _ in range(qdcount):
            _, offset = parse_dns_name(data, offset)
            offset += 4  # QTYPE(2) + QCLASS(2)

        # 遍历 Answer 区域
        for _ in range(ancount):
            if offset >= len(data):
                break
            _, offset = parse_dns_name(data, offset)
            if offset + 10 > len(data):
                break
            rtype, _, _, rdlen = struct.unpack("!HHIH", data[offset:offset + 10])
            offset += 10
            if offset + rdlen > len(data):
                break
            rdata = data[offset:offset + rdlen]

            if rtype == 1 and rdlen == 4:  # A 记录 (IPv4)
                try:
                    ip_str = socket.inet_ntoa(rdata)
                    resolved_ips.append(ip_str)
                except Exception:
                    pass
            elif rtype == 28 and rdlen == 16:  # AAAA 记录 (IPv6)
                try:
                    ip_str = socket.inet_ntop(socket.AF_INET6, rdata)
                    resolved_ips.append(ip_str)
                except Exception:
                    pass
            elif rtype == 5:  # CNAME 记录
                try:
                    cname_target, _ = parse_dns_name(data, offset)
                    if cname_target:
                        cnames.append(cname_target)
                except Exception:
                    pass

            offset += rdlen

        # 若当前应答仅有 CNAME 别名，且递归深度未超限，则自动递归查询 CNAME 目标
        if not resolved_ips and cnames and max_cname_depth > 0:
            for cname in cnames[:2]:
                sub_ips = query_dns_udp(
                    cname,
                    dns_server,
                    qtype=qtype,
                    timeout=timeout,
                    max_cname_depth=max_cname_depth - 1
                )
                resolved_ips.extend(sub_ips)

    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass

    return resolved_ips


def query_system_dns(domain: str) -> List[str]:
    """
    使用系统底层 getaddrinfo 进行本地 DNS 解析作为高可用兜底
    :param domain: 待解析域名
    :return: 解析得到的 IP 列表
    """
    ips: List[str] = []
    try:
        info_list = socket.getaddrinfo(domain, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for item in info_list:
            sockaddr = item[4]
            ip = sockaddr[0]
            if ip and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def is_valid_public_ip(ip_str: str) -> bool:
    """
    公网合法性过滤：排除保留地址、私有局域网、回环、组播及无效 IP
    """
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        if (
            ip_obj.is_loopback
            or ip_obj.is_private
            or ip_obj.is_reserved
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            return False
        return True
    except ValueError:
        return False


class DNSResolver:
    """
    高并发独立 DNS 解析引擎
    支持多线路公共权威 DNS 轮询 + CNAME 自动穿透 + 系统 DNS 兜底 + 公网清洗。
    与业务层彻底解耦，可独立实例化或调用。
    """

    def __init__(
        self,
        dns_servers: Optional[List[str]] = None,
        timeout: float = 0.8,
        max_workers: int = 20
    ):
        self.dns_servers = dns_servers or DEFAULT_UDP_DNS_SERVERS
        self.timeout = timeout
        self.max_workers = max_workers

    def resolve_domain(self, domain: str, resolve_v6: bool = True) -> Set[str]:
        """
        解析单个域名，返回其关联的所有公网有效 IP（去重集合）
        """
        clean_domain = domain.strip().lower()
        if not clean_domain:
            return set()

        found_ips: Set[str] = set()

        # 1. 优先使用公共权威 DNS 池轮询查询 IPv4 A 记录
        for server in self.dns_servers[:4]:
            try:
                for ip in query_dns_udp(clean_domain, server, qtype=1, timeout=self.timeout):
                    if is_valid_public_ip(ip):
                        found_ips.add(ip)
            except Exception:
                pass
            if len(found_ips) >= 2:
                break

        # 2. 如果开启了 IPv6，查询 AAAA 记录
        if resolve_v6:
            for server in self.dns_servers[:2]:
                try:
                    for ip in query_dns_udp(clean_domain, server, qtype=28, timeout=self.timeout):
                        if is_valid_public_ip(ip):
                            found_ips.add(ip)
                except Exception:
                    pass

        # 3. 系统本地 DNS 兜底补充
        for ip in query_system_dns(clean_domain):
            if is_valid_public_ip(ip):
                found_ips.add(ip)

        return found_ips

    def resolve_batch(
        self,
        domains: List[str],
        resolve_v6: bool = True
    ) -> Dict[str, Set[str]]:
        """
        批量多线程并发解析一组域名
        :param domains: 域名列表
        :param resolve_v6: 是否包含 IPv6 AAAA 记录
        :return: 字典映射 { domain: Set[ip, ...] }
        """
        unique_domains = list({d.strip().lower() for d in domains if d.strip()})
        results: Dict[str, Set[str]] = {}

        if not unique_domains:
            return results

        logger.info(f"===> 开始多线程批量 DNS 解析，域名数: {len(unique_domains)} 个，并发线程数: {self.max_workers}")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_domain = {
                executor.submit(self.resolve_domain, d, resolve_v6): d
                for d in unique_domains
            }
            for future in as_completed(future_to_domain):
                domain = future_to_domain[future]
                try:
                    ips = future.result()
                    if ips:
                        results[domain] = ips
                except Exception as e:
                    logger.debug(f"域名 [{domain}] 解析异常: {e}")

        logger.info(f"批量 DNS 解析完成，成功解析出 IP 的域名数: {len(results)} / {len(unique_domains)}")
        return results
