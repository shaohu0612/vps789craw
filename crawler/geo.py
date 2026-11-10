"""
通用 IP / 域名地理位置高精度识别与元数据增强模块
优先加载 IP2Location 离线库查询，未命中或无离线库时采用高可用在线 API (批量/单项) 兜底解析并中文化。
"""

import ipaddress
import logging
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests

logger = logging.getLogger(__name__)

# 常见国家/地区英文及 ISO 代码到中文的标准映射字典 (复用自 E:\myip\modules\geo\resolver.py)
COUNTRY_CN_MAP: Dict[str, str] = {
    "United States": "美国", "US": "美国", "USA": "美国",
    "China": "中国", "CN": "中国",
    "Hong Kong": "香港", "HK": "香港",
    "Taiwan": "台湾", "TW": "台湾",
    "Japan": "日本", "JP": "日本",
    "Singapore": "新加坡", "SG": "新加坡",
    "South Korea": "韩国", "KR": "韩国", "Korea": "韩国", "Korea, Republic of": "韩国",
    "Germany": "德国", "DE": "德国",
    "United Kingdom": "英国", "GB": "英国", "UK": "英国",
    "France": "法国", "FR": "法国",
    "Canada": "加拿大", "CA": "加拿大",
    "Australia": "澳大利亚", "AU": "澳大利亚",
    "Netherlands": "荷兰", "NL": "荷兰",
    "Russia": "俄罗斯", "RU": "俄罗斯",
    "India": "印度", "IN": "印度",
    "Brazil": "巴西", "BR": "巴西",
    "Malaysia": "马来西亚", "MY": "马来西亚",
    "Thailand": "泰国", "TH": "泰国",
    "Vietnam": "越南", "VN": "越南",
    "Philippines": "菲律宾", "PH": "菲律宾",
    "Indonesia": "印度尼西亚", "ID": "印度尼西亚",
    "Macau": "澳门", "MO": "澳门"
}

# 常见国际大都市中英文映射 (复用自 E:\myip\modules\geo\resolver.py)
CITY_CN_MAP: Dict[str, str] = {
    "san jose": "圣何塞", "san francisco": "旧金山", "los angeles": "洛杉矶",
    "new york": "纽约", "seattle": "西雅图", "chicago": "芝加哥", "dallas": "达拉斯",
    "washington": "华盛顿", "miami": "迈阿密", "atlanta": "亚特兰大", "denver": "丹佛",
    "phoenix": "凤凰城", "newark": "纽瓦克", "ashburn": "阿什本", "honolulu": "檀香山",
    "boston": "波士顿", "são paulo": "圣保罗", "sao paulo": "圣保罗", "hyderabad": "海得拉巴",
    "tokyo": "东京", "osaka": "大阪", "fukuoka": "福冈", "nagoya": "名古屋",
    "sapporo": "札幌", "kobe": "神户", "kyoto": "京都", "yokohama": "横滨", "okinawa": "冲绳",
    "hong kong": "香港", "hongkong": "香港",
    "taipei": "台北", "taichung": "台中", "kaohsiung": "高雄", "tainan": "台南",
    "hsinchu": "新竹", "taoyuan": "桃园", "keelung": "基隆", "chiayi": "嘉义",
    "singapore": "新加坡",
    "seoul": "首尔", "incheon": "仁川", "busan": "釜山", "daegu": "大邱",
    "daejeon": "大田", "gwangju": "光州", "chuncheon": "春川", "suwon": "水原",
    "frankfurt": "法兰克福", "frankfurt am main": "法兰克福", "munich": "慕尼黑",
    "berlin": "柏林", "dusseldorf": "杜塞尔多夫", "hamburg": "汉堡",
    "london": "伦敦", "manchester": "曼彻斯特", "edinburgh": "爱丁堡",
    "paris": "巴黎", "marseille": "马赛", "lyon": "里昂",
    "amsterdam": "阿姆斯特丹", "rotterdam": "鹿特丹",
    "sydney": "悉尼", "melbourne": "墨尔本", "brisbane": "布里斯班", "perth": "珀斯",
    "toronto": "多伦多", "vancouver": "温哥华", "montreal": "蒙特利尔", "calgary": "卡尔加里",
    "beijing": "北京", "shanghai": "上海", "guangzhou": "广州", "shenzhen": "深圳",
    "hangzhou": "杭州", "chengdu": "成都", "nanjing": "南京", "wuhan": "武汉",
    "bangkok": "曼谷", "kuala lumpur": "吉隆坡", "hanoi": "河内", "ho chi minh": "胡志明",
    "manila": "马尼拉", "jakarta": "雅加达", "mumbai": "孟买", "delhi": "德里"
}


@dataclass
class GeoInfo:
    """节点地理位置信息模型"""
    country_code: str
    country: str
    city: str

    @property
    def geo_text(self) -> str:
        """
        组合格式: 国家简码-国家 城市
        若无法确认城市，确认国家即可: 国家简码-国家
        """
        clean_city = (self.city or "").strip()
        if not clean_city or clean_city in ("未知城市", "未知", "-", "None", "null"):
            return f"{self.country_code}-{self.country}"
        return f"{self.country_code}-{self.country} {clean_city}"


class GeoResolver:
    """
    IP 地理位置解析器
    支持 IP2Location 离线库优先查询 + 在线 API (批量/单项) 兜底解析与中文化翻译。
    """

    def __init__(self, bin_path: Optional[str] = None):
        self.ip2location_db = None
        self._init_offline_db(bin_path)

    def _init_offline_db(self, bin_path: Optional[str]) -> None:
        """尝试初始化加载 IP2Location 离线库"""
        candidate_paths: List[Path] = []
        if bin_path:
            candidate_paths.append(Path(bin_path))
        env_path = os.getenv("IP2LOCATION_BIN_PATH")
        if env_path:
            candidate_paths.append(Path(env_path))
        # 兼容 E:\myip 典型路径与当前工作区路径
        candidate_paths.extend([
            Path("data/ip2location/IP2LOCATION-LITE-DB3.BIN"),
            Path("E:/myip/data/ip2location/IP2LOCATION-LITE-DB3.BIN"),
        ])

        for p in candidate_paths:
            if p.exists() and p.is_file():
                try:
                    import IP2Location
                    self.ip2location_db = IP2Location.IP2Location(str(p))
                    logger.info(f"成功加载 IP2Location 离线库: {p}")
                    return
                except Exception as e:
                    logger.debug(f"尝试加载离线库 {p} 失败: {e}")

    def translate_country(self, country_raw: str, country_code: Optional[str] = None) -> str:
        """国家名称转换为中文"""
        clean = (country_raw or "").strip()
        code = (country_code or "").strip().upper()
        if not clean or clean.lower() in ("-", "unknown", "n/a", "null", "none"):
            return COUNTRY_CN_MAP.get(code, "未知国家")
        return COUNTRY_CN_MAP.get(clean, COUNTRY_CN_MAP.get(code, clean))

    def translate_city(self, city_raw: str) -> str:
        """城市名称转换为中文"""
        clean = (city_raw or "").strip()
        lower_clean = clean.lower()
        if not clean or lower_clean in ("-", "unknown", "n/a", "null", "none"):
            return "未知城市"
        if lower_clean in CITY_CN_MAP:
            return CITY_CN_MAP[lower_clean]
        if clean in CITY_CN_MAP:
            return CITY_CN_MAP[clean]
        if lower_clean.endswith(" city"):
            base = lower_clean[:-5].strip()
            if base in CITY_CN_MAP:
                return CITY_CN_MAP[base]
        return clean

    def query_offline(self, ip: str) -> Optional[GeoInfo]:
        """使用 IP2Location 离线库查询"""
        if not self.ip2location_db:
            return None
        clean_ip = ip.strip("[]")
        try:
            rec = self.ip2location_db.get_all(clean_ip)
            if not rec:
                return None
            country_code = getattr(rec, "country_short", "") or "XX"
            country_raw = getattr(rec, "country_long", "")
            city_raw = getattr(rec, "city", "")

            country_cn = self.translate_country(country_raw, country_code)
            city_cn = self.translate_city(city_raw)
            return GeoInfo(
                country_code=country_code.upper() if country_code != "-" else "XX",
                country=country_cn,
                city=city_cn
            )
        except Exception:
            return None

    def query_online_batch(self, ips: List[str], timeout: int = 8) -> Dict[str, GeoInfo]:
        """使用 ip-api.com/batch 批量高效解析 (每次最多 100 个 IP，免频控限制)"""
        results: Dict[str, GeoInfo] = {}
        if not ips:
            return results

        chunk_size = 100
        for i in range(0, len(ips), chunk_size):
            chunk = ips[i:i + chunk_size]
            payload = [{"query": ip.strip("[]")} for ip in chunk]
            try:
                resp = requests.post(
                    "http://ip-api.com/batch?lang=zh-CN",
                    json=payload,
                    timeout=timeout,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data:
                        query_ip = item.get("query")
                        if not query_ip:
                            continue
                        if item.get("status") == "success":
                            code = (item.get("countryCode") or "XX").upper()
                            country = self.translate_country(item.get("country", ""), code)
                            city = self.translate_city(item.get("city", ""))
                            results[query_ip] = GeoInfo(country_code=code, country=country, city=city)
            except Exception as e:
                logger.warning(f"在线批量 GeoIP 查询异常: {e}")

        return results

    def query_single_online(self, ip: str, timeout: int = 5) -> GeoInfo:
        """单项在线 API 兜底解析"""
        clean_ip = ip.strip("[]")
        # 1. 尝试 ip-api.com
        try:
            url = f"http://ip-api.com/json/{clean_ip}?lang=zh-CN"
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    code = (data.get("countryCode") or "XX").upper()
                    country = self.translate_country(data.get("country", ""), code)
                    city = self.translate_city(data.get("city", ""))
                    return GeoInfo(country_code=code, country=country, city=city)
        except Exception:
            pass

        # 2. 备选 ipwhois.app
        try:
            url = f"https://ipwhois.app/json/{clean_ip}"
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success", False):
                    code = (data.get("country_code") or "XX").upper()
                    country = self.translate_country(data.get("country", ""), code)
                    city = self.translate_city(data.get("city", ""))
                    return GeoInfo(country_code=code, country=country, city=city)
        except Exception:
            pass

        return GeoInfo(country_code="XX", country="未知国家", city="未知城市")

    def resolve_all(self, ips: List[str]) -> Dict[str, GeoInfo]:
        """
        综合解析 IP 列表地理信息: 离线库优先 -> 在线批量查询 -> 单项兜底
        """
        unique_ips = list(dict.fromkeys(ips))
        results: Dict[str, GeoInfo] = {}
        missing_ips: List[str] = []

        # 1. 尝试离线库
        for ip in unique_ips:
            geo = self.query_offline(ip)
            if geo and geo.country != "未知国家":
                results[ip] = geo
            else:
                missing_ips.append(ip)

        # 2. 尝试批量在线 API
        if missing_ips:
            logger.info(f"离线库未命中 {len(missing_ips)} 个 IP，启用在线批量查询...")
            online_batch = self.query_online_batch(missing_ips)
            for ip, geo in online_batch.items():
                results[ip] = geo

            # 仍未命中的单项补救
            still_missing = [ip for ip in missing_ips if ip not in results or results[ip].country == "未知国家"]
            if still_missing:
                logger.info(f"在线批量仍有 {len(still_missing)} 个 IP 缺失，使用单项兜底接口...")
                for ip in still_missing:
                    results[ip] = self.query_single_online(ip)

        # 确保所有入参 IP 均有对应结果
        for ip in unique_ips:
            if ip not in results:
                results[ip] = GeoInfo(country_code="XX", country="未知国家", city="未知城市")

        return results


def resolve_domain_to_ip(domain: str, timeout: float = 3.0) -> Optional[str]:
    """
    将域名解析为 A 记录 IPv4 地址
    """
    clean_domain = domain.strip().split("/")[0].split(":")[0]
    try:
        ip = socket.gethostbyname(clean_domain)
        return ip
    except Exception:
        return None


def batch_resolve_domains(domains: List[str], max_workers: int = 20) -> Dict[str, Optional[str]]:
    """
    并发解析多个域名至对应 IP
    """
    results: Dict[str, Optional[str]] = {}
    unique_domains = list(dict.fromkeys(domains))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(resolve_domain_to_ip, d): d for d in unique_domains}
        for future in futures:
            d = futures[future]
            try:
                results[d] = future.result()
            except Exception:
                results[d] = None

    return results
