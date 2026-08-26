"""
API 客户端模块单元测试（Mock 接口与分页）
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from crawler.client import VPS789Client
from crawler.crypto import des_cbc_encrypt, DEFAULT_DECRYPT_KEY


def test_fetch_page_success():
    """
    测试单页抓取与自动解密流程
    """
    mock_data = {
        "content": [
            {"id": 1, "ip": "www.shopify.com", "pingPort": 443, "providerUrl": None},
            {"id": 2, "ip": "104.21.20.210", "pingPort": 443, "providerUrl": "测试"}
        ],
        "totalElements": 2,
        "totalPages": 1
    }
    encrypted_msg = des_cbc_encrypt(json.dumps(mock_data), key_str=DEFAULT_DECRYPT_KEY)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": 0,
        "message": encrypted_msg
    }

    client = VPS789Client()
    with patch.object(client.session, "post", return_value=mock_response):
        res = client.fetch_page(remarks_type="domain", page_number=1, page_size=10)
        assert res["totalElements"] == 2
        assert len(res["content"]) == 2
        assert res["content"][0]["ip"] == "www.shopify.com"


def test_fetch_page_api_error():
    """
    测试接口返回业务非零错误码
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": 500,
        "msg": "内部服务器错误"
    }

    client = VPS789Client()
    with patch.object(client.session, "post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="业务错误"):
            client.fetch_page(remarks_type="domain", page_number=1)


def test_fetch_all_pagination():
    """
    测试全量分页聚合
    """
    page1_data = {
        "content": [{"id": 1, "ip": "node1.com", "pingPort": 443}],
        "totalElements": 2
    }
    page2_data = {
        "content": [{"id": 2, "ip": "node2.com", "pingPort": 443}],
        "totalElements": 2
    }

    client = VPS789Client()
    with patch.object(client, "fetch_page", side_effect=[page1_data, page2_data]):
        nodes = client.fetch_all(remarks_type="domain", page_size=1)
        assert len(nodes) == 2
        assert nodes[0]["ip"] == "node1.com"
        assert nodes[1]["ip"] == "node2.com"
