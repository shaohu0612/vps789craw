"""
VPS789 API 通信与数据抓取客户端
实现鉴权 Token 生成、API 交互、DES 响应解密与自动分页抓取。
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from crawler.crypto import des_cbc_decrypt, generate_auth_token

logger = logging.getLogger(__name__)


class VPS789Client:
    """
    VPS789 平台 API 交互客户端
    """

    def __init__(
        self,
        base_url: str = "https://vps789.com",
        timeout: int = 15,
        max_retries: int = 3,
        user_agent: Optional[str] = None
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

        # 配置自动重试机制
        retries = Retry(
            total=max_retries,
            backoff_factor=1.0,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

    def fetch_page(
        self,
        remarks_type: str = "domain",
        page_number: int = 1,
        page_size: int = 200
    ) -> Dict[str, Any]:
        """
        分页请求单页节点数据并解密。

        :param remarks_type: 筛选类型，"domain"（域名）或 "ip"（优选 IP）
        :param page_number: 页码（从 1 开始）
        :param page_size: 每页数量，默认 200
        :return: 解密后的分页字典对象（包含 content, totalElements 等）
        """
        url = f"{self.base_url}/public/cfMonitorList"
        token = generate_auth_token()

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": self.user_agent,
            "token": token,
            "Accept": "application/json, text/plain, */*"
        }

        payload = {
            "criteria": {
                "remarks": {
                    "contains": remarks_type
                }
            },
            "page": {
                "number": page_number,
                "size": page_size,
                "sort": ["createdTime,asc"]
            }
        }

        logger.debug(f"正在请求 VPS789 API: {url} | remarks={remarks_type} | page={page_number}")

        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            res_json = resp.json()
        except requests.RequestException as e:
            logger.error(f"网络请求失败: {e}")
            raise RuntimeError(f"请求 VPS789 API 失败: {e}") from e
        except json.JSONDecodeError as e:
            logger.error(f"响应解析 JSON 失败: {resp.text[:200]}")
            raise RuntimeError("VPS789 API 返回非 JSON 格式数据") from e

        code = res_json.get("code")
        if code != 0:
            err_msg = res_json.get("msg") or res_json.get("message") or f"未知错误 code={code}"
            logger.error(f"VPS789 接口返回业务错误: {err_msg}")
            raise RuntimeError(f"VPS789 API 业务错误: {err_msg}")

        encrypted_message = res_json.get("message")
        if not encrypted_message:
            logger.warning("VPS789 接口返回数据为空或未加密")
            return {"content": [], "totalElements": 0}

        try:
            decrypted_text = des_cbc_decrypt(encrypted_message)
            data = json.loads(decrypted_text)
            return data
        except Exception as e:
            logger.error(f"数据解密或解析失败: {e}")
            raise RuntimeError(f"解密 VPS789 数据失败: {e}") from e

    def fetch_all(
        self,
        remarks_type: str = "domain",
        page_size: int = 200,
        max_pages: int = 50
    ) -> List[Dict[str, Any]]:
        """
        自动分页获取指定类型的全部节点数据。

        :param remarks_type: 筛选类型，"domain" 或 "ip"
        :param page_size: 每页数量
        :param max_pages: 最大拉取页数安全保护
        :return: 全量原始节点列表
        """
        all_items: List[Dict[str, Any]] = []
        page = 1

        logger.info(f"开始全量拉取类型 [{remarks_type}] 数据...")

        while page <= max_pages:
            data = self.fetch_page(remarks_type=remarks_type, page_number=page, page_size=page_size)
            items = data.get("content", [])
            total_elements = data.get("totalElements", 0)

            if not items:
                break

            all_items.extend(items)
            logger.info(f"成功拉取第 {page} 页: 获得 {len(items)} 条数据 (累计 {len(all_items)}/{total_elements})")

            if len(all_items) >= total_elements or len(items) < page_size:
                break

            page += 1
            # 避免对目标服务器造成并发压力
            time.sleep(0.3)

        logger.info(f"拉取完成: 类型 [{remarks_type}] 共获取 {len(all_items)} 条记录")
        return all_items
