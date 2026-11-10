# UOUIN 麒麟优选 IP 爬虫逆向分析与系统设计方案

---

## 一、 背景与业务目标

### 1.1 业务背景
在本项目（Cloudflare 优选节点采集与发布系统）中，除了原有的 VPS789 平台节点采集外，需要扩展接入 `api.uouin.com` 提供的“麒麟优选”节点数据源（[https://api.uouin.com/cloudflare.html](https://api.uouin.com/cloudflare.html)）。

通过自动化采集该站点的优质 Cloudflare Anycast IP，并进行网络质量与速度门限过滤、高精地理信息解析汉化、标准化格式输出，并借助 GitHub Actions 独立定时器实现每 6 小时自动抓取与推送，向订阅客户端提供高可用、高带宽的优选 IP 列表。

### 1.2 最终目标产物
- **目标输出文件**：`uouin-bestip`（位于仓库根目录下）
- **Raw 订阅地址**：`https://raw.githubusercontent.com/shaohu0612/vps789craw/refs/heads/main/uouin-bestip`
- **更新周期**：每 6 小时自动定时刷新与推送

---

## 二、 页面逆向分析与数据刷新机制

### 2.1 初始访问“旧数据”成因
当直接使用常规 HTTP GET 请求访问目标 URL `https://api.uouin.com/cloudflare.html` 时，服务端渲染返回的 HTML 表格中包含固定的静态数据。
经审查页面源码发现：
- 静态表格中的节点测速时间戳均停留在 `2024/04/09`（历史缓存数据）。
- 表格上方包含提示信息：`<fieldset>正在加载最新的CloudFlare优选IP数据中...</fieldset>`。
- 页面底部引入了两个关键脚本：
  ```html
  <script type="text/javascript" src="//static-api.urlce.com/public/js/md5.js"></script>
  <script type="text/javascript" src="//static-api.urlce.com/public/js/cloudflare.js"></script>
  ```
这表明页面在浏览器中加载完毕后，会通过 JavaScript 异步发起动态请求以获取最新的优选节点数据并刷新 DOM。

### 2.2 JavaScript 逆向与加密算法解析
通过提取并反混淆 `cloudflare.js`（基于 `jsjiami.com.v6` 保护机制），还原出了前端获取最新测速数据的签名机制与请求流程：

1. **双层 MD5 动态密钥签名算法**：
   - 获取当前 Unix 毫秒级时间戳：`now_ms = int(time.time() * 1000)`
   - 第一层 MD5 哈希：
     $$\text{step1} = \text{MD5}(\text{"DdlTxtN0sUOu"})$$
     得到固定的 32 位小写 Hex 字符串：`13e70d472cbf0bb4f1a6f81014abdf05`
   - 第二层 MD5 哈希（拼接私钥与动态时间戳）：
     $$\text{key} = \text{MD5}(\text{step1} + \text{"70cloudflareapikey"} + \text{now\_ms})$$
2. **动态 API 请求参数**：
   - 请求方法：`GET`
   - 请求 URL：`https://api.uouin.com/index.php/index/Cloudflare?key={key}&time={now_ms}`
   - 核心请求头：
     ```http
     User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36
     Accept: application/json, text/plain, */*
     Referer: https://api.uouin.com/cloudflare.html
     ```
     > **注意**：`Referer` 标头为服务端防盗链校验项，若缺失会导致拒绝响应。
3. **响应载荷结构**：
   服务端校验时间戳与签名有效后，返回实时测试 JSON 数据：
   ```json
   {
     "code": "200",
     "msg": "获取成功",
     "data": {
       "bgp": { "info": [ ... ] },
       "ctcc": { "info": [ ... ] },
       "cmcc": { "info": [ ... ] },
       "cucc": { "info": [ ... ] },
       "ipv6": { "info": [ ... ] }
     }
   }
   ```
   其中包含五大维度的实时节点列表，每个节点包含 `ip`、`loss`（丢包率）、`ping`（平均延迟）、`speed`（实测下载速度，如 `61.14mb/s`）及 `bandwidth` 等指标。

---

## 三、 数据清洗、格式化与 Geo 增强规范

### 3.1 格式规范
输出格式严格统一为：
```text
ip:端口#麒麟优选-线路-国家简码-国家 城市-延迟-速度
```

### 3.2 字段处理细则
1. **主机标识与端口**：
   - 页面及接口未显示端口，**端口统一默认为 443**。
   - IPv4 节点格式：`ip:443`（例如 `104.18.34.111:443`）。
   - IPv6 节点格式：按照标准网络 URI 规范包裹方括号 `[ip]:443`（例如 `[2a06:98c1:310e:588a:83f7:dc81:a024:33b7]:443`）。
2. **前缀标识**：
   - 固定使用 `麒麟优选-` 前缀。
3. **线路名称映射**：
   - `ctcc` $\rightarrow$ `电信`
   - `cucc` $\rightarrow$ `联通`
   - `cmcc` $\rightarrow$ `移动`
   - `bgp` $\rightarrow$ `多线`
   - `ipv6` $\rightarrow$ `IPV6`
4. **速度门限筛选**：
   - 正则提取测速字符串中的浮点数值（单位 mb/s）。
   - **严格筛选速度 $\ge 10.0\,\text{mb/s}$ 的节点**，低于该阈值的节点直接淘汰。
   - 自动排除私网地址、环回地址与非法格式 IP。
   - 若同一 IP 出现在多个线路分类中，去重并保留测速最高记录。
5. **地理位置信息（国家简码-国家 城市）**：
   - 格式说明：`国家简码-国家 城市`（国家名称与城市名称之间使用单个半角空格分隔，如 `US-美国 圣何塞`、`CA-加拿大 多伦多`）。
   - 解析策略（复用自 `E:\myip` 项目成熟的高可用方案）：
     1. **离线查询优先**：支持通过 `IP2Location` 离线 BIN 库快速本地解析。
     2. **在线批量查询兜底**：使用 `http://ip-api.com/batch?lang=zh-CN` 批量接口（单次 POST 即可解析多达 100 个 IP，耗时约 1 秒，无单 IP 频控限制）。
     3. **单项接口二级兜底**：备选 `ipwhois.app` 与 `ipapi.co`。
     4. **国际化中文字典归一化**：内置 `COUNTRY_CN_MAP` 与 `CITY_CN_MAP`，即使在线 API 返回英文地名，亦可准确翻译为中文。
6. **结果排序**：
   - **最终结果严格按照下载速度倒序排列（从高到低）**，确保订阅客户端优先获取最高质量的高速节点。

---

## 四、 系统架构与模块设计

### 4.1 目录组织结构
```
vps789craw/
├── doc/
│   └── uouin爬虫分析设计方案.md   # 本设计分析方案文档 (配置忽略提交)
├── crawler/
│   ├── __init__.py
│   ├── crypto.py                  # VPS789 加密与签名算法
│   ├── client.py                  # VPS789 客户端
│   ├── formatter.py               # VPS789 节点格式化引擎
│   ├── uouin.py                   # UOUIN 麒麟优选逆向采集、Geo 增强与排序引擎
│   └── main.py                    # 全局 CLI 入口
├── tests/
│   ├── test_crypto.py
│   ├── test_client.py
│   ├── test_formatter.py
│   └── test_uouin.py              # UOUIN 核心逻辑全场景单元测试
├── uouin-bestip                   # 麒麟优选输出文件
├── AGENTS.md / agent.md           # Agent 全局规范文档
├── README.md                      # 项目说明文档
└── .github/
    └── workflows/
        ├── crawl-domains.yml      # VPS789 域名定时任务
        ├── crawl-bestip.yml       # VPS789 IP 定时任务
        └── crawl-uouin.yml        # UOUIN 麒麟优选 IP 独立定时工作流
```

### 4.2 核心类与方法
- `UOUINCrawler`：
  - `generate_signature(now_ms)`: 计算双层 MD5 签名。
  - `fetch_api_data()`: 发起带动态防伪鉴权头的 HTTP GET 请求并处理重试。
  - `extract_raw_nodes(data, min_speed)`: 线路分类展开、速度筛选、格式解析与去重。
  - `format_node_line(node, geo, default_port)`: 组装输出标准订阅行。
  - `crawl_and_format(min_speed, default_port)`: 完整采集、Geo 增强、排序流。
- `GeoResolver`：
  - `query_offline(ip)`: IP2Location 本地查询。
  - `query_online_batch(ips)`: `ip-api.com/batch` 批量查询。
  - `translate_country(raw, code)` / `translate_city(raw)`: 地名中文化。

---

## 五、 GitHub Actions 独立定时调度与自动化同步

在 `.github/workflows/crawl-uouin.yml` 中配置独立的自动化工作流：
1. **错峰调度**：
   - Cron 表达式：`45 */6 * * *`（每 6 小时 45 分触发，与 VPS789 采集任务错开）。
2. **手动调试支持**：
   - 支持 `workflow_dispatch` 手动触发，并支持在控制台动态配置 `min_speed` 速度过滤门限。
3. **智能提交与推送**：
   - 采集完成后，使用 `git status --porcelain uouin-bestip` 比对文件内容。
   - 仅在内容有实际变动时才执行 `git commit` 与 `git push`，避免产生无效空提交。
   - 将采集统计指标（时间、节点总数、速度排名前 5 的节点预览）追加到 `$GITHUB_STEP_SUMMARY`，提供直观的运行报告。

---

## 六、 验证与交付状态

1. **自动化测试**：
   全量单元测试（`tests/test_uouin.py` 等）通过率 100%（22/22 passed）。
2. **实际运行输出**：
   `uouin-bestip` 成功生成并按照速度严格倒序排列：
   ```text
   104.18.34.111:443#麒麟优选-电信-CA-加拿大 多伦多-75.26ms-71.27mb/s
   104.18.42.50:443#麒麟优选-电信-CA-加拿大 多伦多-106.15ms-67.15mb/s
   172.64.229.198:443#麒麟优选-电信-CA-加拿大 多伦多-52.48ms-60.69mb/s
   [2a06:98c1:310e:588a:83f7:dc81:a024:33b7]:443#麒麟优选-IPV6-GB-英国 伦敦-45.67ms-30.38mb/s
   [2a06:98c1:3109:0:9e:ec14:da26:c9c1]:443#麒麟优选-IPV6-GB-英国 伦敦-45.18ms-29.80mb/s
   172.64.79.103:443#麒麟优选-联通-CA-加拿大 多伦多-173.15ms-21.82mb/s
   ...
   ```
