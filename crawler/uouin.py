"""
api.uouin.com Cloudflare 优选 IP 采集、清洗与发布模块 (麒麟优选)
逆向解析 cloudflare.js 实时时间戳与 MD5 双层加密密钥签名算法，并融合 Geo 地理位置增强与速度过滤。
"""

import argparse
import hashlib
import ipaddress
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests

from crawler.geo import (
    COUNTRY_CN_MAP,
    CITY_CN_MAP,
    GeoInfo,
    GeoResolver,
)

logger = logging.getLogger(__name__)

# 线路代码与中文名称映射
LINE_NAME_MAP: Dict[str, str] = {
    "ctcc": "电信",
    "cucc": "联通",
    "cmcc": "移动",
    "bgp": "多线",
    "ipv6": "IPV6",
}


@dataclass
class UOUINRawNode:
    """UOUIN 原始节点数据模型"""
    ip: str
    line: str
    loss: str
    ping: str
    speed_str: str
    speed_value: float
    latency_value: float
    bandwidth: str


class UOUINCrawler:
    """
    麒麟优选 (api.uouin.com) 优选 IP 采集器
    """

    BASE_URL = "https://api.uouin.com"
    REFERER_URL = "https://api.uouin.com/cloudflare.html"

    def __init__(self, timeout: int = 15, geo_resolver: Optional[GeoResolver] = None):
        self.timeout = timeout
        self.geo_resolver = geo_resolver or GeoResolver()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": self.REFERER_URL
        })

    @staticmethod
    def generate_signature(now_ms: Optional[int] = None) -> Tuple[int, str]:
        """
        逆向解析 cloudflare.js 实时时间戳与 MD5 双层加密密钥签名算法:
        step1 = md5("DdlTxtN0sUOu")
        step2 = md5(step1 + "70cloudflareapikey" + now_ms)
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        step1 = hashlib.md5("DdlTxtN0sUOu".encode("utf-8")).hexdigest()
        step2 = f"{step1}70cloudflareapikey{now_ms}"
        hash_val = hashlib.md5(step2.encode("utf-8")).hexdigest()
        return now_ms, hash_val

    def fetch_api_data(self) -> Dict[str, Any]:
        """
        根据动态签名请求接口获取实时刷新后的数据
        接口地址: /index.php/index/Cloudflare?key={key}&time={time}
        """
        now_ms, hash_val = self.generate_signature()
        api_url = f"{self.BASE_URL}/index.php/index/Cloudflare?key={hash_val}&time={now_ms}"
        logger.info(f"正在请求 UOUIN 动态刷新接口: {api_url}")

        for attempt in range(1, 4):
            try:
                resp = self.session.get(api_url, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    if str(data.get("code")) == "200" or data.get("code") == 200:
                        logger.info("成功获取 UOUIN 实时优选节点数据")
                        return data.get("data", {})
                    else:
                        logger.warning(f"接口返回业务错误: code={data.get('code')}, msg={data.get('msg')}")
                else:
                    logger.warning(f"接口响应状态异常: HTTP {resp.status_code} (尝试 {attempt}/3)")
            except Exception as e:
                logger.warning(f"接口请求异常 (尝试 {attempt}/3): {e}")

            if attempt < 3:
                time.sleep(1.5 * attempt)

        return {}

    @staticmethod
    def parse_numeric_speed(speed_str: str) -> float:
        """从速度字符串中提取数值 (例如 '61.14mb/s' -> 61.14)"""
        m = re.search(r"(\d+(?:\.\d+)?)", speed_str or "")
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return 0.0

    @staticmethod
    def parse_numeric_latency(ping_str: str) -> float:
        """从延迟字符串中提取数值 (例如 '51.97ms' -> 51.97)"""
        m = re.search(r"(\d+(?:\.\d+)?)", ping_str or "")
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return 9999.0

    def extract_raw_nodes(
        self,
        data: Dict[str, Any],
        min_speed: float = 10.0
    ) -> List[UOUINRawNode]:
        """
        解析 API 返回各线路节点并过滤速度 >= min_speed
        """
        raw_nodes: List[UOUINRawNode] = []
        seen_ips = set()

        for cat_key, line_info in data.items():
            if not isinstance(line_info, dict):
                continue
            line_name = LINE_NAME_MAP.get(cat_key, cat_key)
            items = line_info.get("info", [])
            for it in items:
                ip_str = str(it.get("ip", "")).strip()
                if not ip_str:
                    continue

                speed_str = str(it.get("speed", "")).strip()
                speed_val = self.parse_numeric_speed(speed_str)

                # 速度过滤
                if speed_val < min_speed:
                    continue

                # IP 合法性过滤
                clean_ip = ip_str.strip("[]")
                try:
                    ip_obj = ipaddress.ip_address(clean_ip)
                    if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_reserved or ip_obj.is_multicast:
                        continue
                except ValueError:
                    continue

                # 去重：若同一 IP 多次出现，保留速度较高者
                if clean_ip in seen_ips:
                    continue
                seen_ips.add(clean_ip)

                ping_str = str(it.get("ping", "")).strip()
                loss_str = str(it.get("loss", "")).strip()
                bandwidth_str = str(it.get("bandwidth", "")).strip()
                lat_val = self.parse_numeric_latency(ping_str)

                raw_nodes.append(UOUINRawNode(
                    ip=clean_ip,
                    line=line_name,
                    loss=loss_str,
                    ping=ping_str,
                    speed_str=speed_str,
                    speed_value=speed_val,
                    latency_value=lat_val,
                    bandwidth=bandwidth_str
                ))

        return raw_nodes

    @staticmethod
    def format_node_line(node: UOUINRawNode, geo: GeoInfo, default_port: int = 443) -> str:
        """
        格式化节点为输出格式:
        ip:端口#麒麟优选-线路-国家简码-国家 城市-延迟-速度
        注意：
        1. 页面未显示端口，默认为 443
        2. 若为 IPv6 地址，采用标准 [IPv6]:端口 表达
        """
        clean_ip = node.ip.strip("[]")
        is_ipv6 = ":" in clean_ip
        host_port = f"[{clean_ip}]:{default_port}" if is_ipv6 else f"{clean_ip}:{default_port}"

        # 延迟与速度单元规范化
        ping_display = node.ping if node.ping else f"{node.latency_value:.2f}ms"
        if not ping_display.endswith("ms"):
            ping_display = f"{ping_display}ms"

        speed_display = node.speed_str if node.speed_str else f"{node.speed_value:.2f}mb/s"
        if not speed_display.lower().endswith("b/s"):
            speed_display = f"{speed_display}mb/s"

        line_str = f"{host_port}#麒麟优选-{node.line}-{geo.geo_text}-{ping_display}-{speed_display}"
        return line_str

    def crawl_and_format(
        self,
        min_speed: float = 10.0,
        default_port: int = 443
    ) -> List[Tuple[float, str]]:
        """
        全流程执行：拉取实时数据 -> 提取与过滤 -> 地理位置增强 -> 格式化 -> 按速度倒序排列
        :return: [(speed_value, formatted_line), ...]
        """
        data = self.fetch_api_data()
        if not data:
            logger.warning("未能获取到 UOUIN 接口数据")
            return []

        raw_nodes = self.extract_raw_nodes(data, min_speed=min_speed)
        logger.info(f"速度筛选 (>= {min_speed}mb/s) 命中 {len(raw_nodes)} 个节点")
        if not raw_nodes:
            return []

        # 批量解析地理位置
        all_ips = [n.ip for n in raw_nodes]
        geo_map = self.geo_resolver.resolve_all(all_ips)

        formatted_results: List[Tuple[float, str]] = []
        for n in raw_nodes:
            geo = geo_map.get(n.ip, GeoInfo(country_code="XX", country="未知国家", city="未知城市"))
            line = self.format_node_line(n, geo, default_port=default_port)
            formatted_results.append((n.speed_value, line))

        # 按照速度倒序排列 (从高到低)
        formatted_results.sort(key=lambda x: x[0], reverse=True)
        return formatted_results


def run_uouin_crawl(
    output_path: str = "uouin-bestip",
    min_speed: float = 10.0,
    dry_run: bool = False
) -> int:
    """
    运行麒麟优选采集并写入目标文件
    """
    crawler = UOUINCrawler()
    results = crawler.crawl_and_format(min_speed=min_speed)
    count = len(results)

    logger.info(f"采集与清洗完成，共生成 {count} 条优质麒麟优选节点 (速度 >= {min_speed}mb/s)")

    if dry_run:
        logger.info("[试运行模式] 不写入文件，前 10 行预览:")
        for _, line in results[:10]:
            print(line)
        return count

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        for _, line in results:
            f.write(line + "\n")

    logger.info(f"成功保存到文件: {out_file.resolve()} (共 {count} 行)")
    return count


def main() -> int:
    """命令行主入口"""
    parser = argparse.ArgumentParser(description="api.uouin.com 麒麟优选 IP 自动采集工具")
    parser.add_argument("--min-speed", type=float, default=10.0, help="最低下载速度阈值 (mb/s)，默认 10.0")
    parser.add_argument("--output", default="uouin-bestip", help="输出文件路径，默认根目录 uouin-bestip")
    parser.add_argument("--dry-run", action="store_true", help="试运行模式 (仅控制台打印预览，不落盘)")
    parser.add_argument("--verbose", action="store_true", help="开启详细调试日志")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    try:
        run_uouin_crawl(
            output_path=args.output,
            min_speed=args.min_speed,
            dry_run=args.dry_run
        )
        return 0
    except Exception as e:
        logger.exception(f"执行优选 IP 采集任务失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
