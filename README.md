# Cloudflare 优选节点采集与自动发布系统 (VPS789 & 麒麟优选)

本项目用于自动化定时采集 [vps789.com](https://vps789.com) 与 [api.uouin.com](https://api.uouin.com/cloudflare.html) 的 Cloudflare 优选节点（包含优选域名与优选 IP），经过规范化格式清洗、速度门限过滤与高精地理信息增强后，自动提交发布至 GitHub 仓库 `shaohu0612/vps789craw` 的 `main` 分支。

---

## 一、 输出地址与订阅链接

* **VPS789 优选域名列表**：
  `https://raw.githubusercontent.com/shaohu0612/vps789craw/refs/heads/main/vps789-domains`
* **VPS789 域名转 IP 列表 (高并发DNS解析+Geo增强+速度倒序)**：
  `https://raw.githubusercontent.com/shaohu0612/vps789craw/refs/heads/main/vps789-domains2ip`
* **VPS789 优选 IP 列表**：
  `https://raw.githubusercontent.com/shaohu0612/vps789craw/refs/heads/main/vps789-bestip`
* **UOUIN 麒麟优选 IP 列表 (速度 >= 10mb/s 倒序)**：
  `https://raw.githubusercontent.com/shaohu0612/vps789craw/refs/heads/main/uouin-bestip`

---

## 二、 格式化与清洗规则

### 1. VPS789 节点格式化规则
输出格式统一为：`CF优选IP:端口#前缀-备注`（默认前缀为 `vps789-`）

* **网络质量过滤（优选域名）**：
  * 计算电信、移动、联通三网平均延迟与平均丢包率。**三网平均延迟 > 300ms 或 平均丢包率 > 10% 直接过滤剔除**。
* **端口省略规则**：
  * 若为域名且端口为 `443`，`:端口` 省略。端口非 443 时保留。
  * 若为 IP 地址（IPv4 或 IPv6），`:端口` 绝不可省略。
* **备注处理**：
  * 拼接前缀 `vps789-` 与备注；备注为空时复用域名/IP 字段。

### 2. VPS789 域名转 IP（vps789-domains2ip）规则
部分自建或旧版 Worker 订阅引擎（如旧版 `cfnew`、`edgetunnel`）在拉取域名时会截断 `#` 后面的测速备注。为此系统提供域名转 IP 机制：
* **底层高并发解析**：基于 RFC 1035 UDP 纯原生二进制报文解析，支持公共 DNS 递归穿透与系统 DNS 降级，自动过滤内网及保留地址。
* **指标继承与去重**：继承原优选域名的实测下载速度与延迟；多域名解析至同一 Anycast IP 时，自动保留最高速度最优记录。
* **输出规范**：`IP:443#vps789-国家简码-国家 城市-延迟-速度`，严格按下载速度倒序排列。

### 3. UOUIN 麒麟优选 IP 格式化规则
输出格式统一为：`ip:端口#麒麟优选-线路-国家简码-国家 城市-延迟-速度`

* **页面刷新机制与逆向签名**：
  * 避开页面直接返回的 2024 年旧数据，逆向解析 `cloudflare.js` 的实时时间戳与 MD5 双层加密密钥签名算法 (`key = md5(md5('DdlTxtN0sUOu') + '70cloudflareapikey' + now_ms)`)，实时拉取当日最新测速数据。
* **速度过滤与倒序排列**：
  * **严格筛选速度 `>= 10.0mb/s` 的优质 IP**。
  * **最终输出文件严格按照速度倒序排列**（高速度 IP 排在最前）。
* **端口规范**：
  * 页面未显示端口，**端口统一默认为 443**。
  * IPv4 格式：`ip:443`（例如 `104.18.34.111:443`）
  * IPv6 格式：`[ip]:443`（例如 `[2a06:98c1:310e:588a:83f7:dc81:a024:33b7]:443`）
* **地理位置增强**：
  * 支持 IP2Location 离线库优先查询 + 在线 API (`http://ip-api.com/batch?lang=zh-CN`、`ipwhois.app` 等) 兜底解析。
  * 结合内置中文字典归一化为 `国家简码-国家 城市`（如 `US-美国 圣何塞`、`CA-加拿大 多伦多`、`GB-英国 伦敦`）。
* **示例**：
  * `104.18.34.111:443#麒麟优选-电信-CA-加拿大 多伦多-75.26ms-71.27mb/s`
  * `[2a06:98c1:310e:588a:83f7:dc81:a024:33b7]:443#麒麟优选-IPV6-GB-英国 伦敦-45.67ms-30.38mb/s`

---

## 三、 项目架构

```
vps789craw/
├── AGENTS.md                  # 全局 Agent 指导与开发规范
├── README.md                  # 项目说明与部署指南
├── requirements.txt           # Python 依赖声明
├── .env.example               # 环境变量配置示例
├── vps789-domains             # VPS789 优选域名最新输出文件
├── vps789-bestip              # VPS789 优选 IP 最新输出文件
├── uouin-bestip               # UOUIN 麒麟优选 IP 最新输出文件 (速度>=10mb/s 倒序)
├── vps789-domains2ip          # VPS789 域名转 IP 最新输出文件 (高并发DNS解析+Geo增强+速度倒序)
├── crawler/
│   ├── __init__.py
│   ├── crypto.py              # VPS789 动态 DES-CBC 加解密与鉴权 Token 生成
│   ├── client.py              # VPS789 API 客户端（自动重试、分页拉取与解密）
│   ├── geo.py                 # 通用 IP/域名高精度地理信息与中文化模块 (GeoResolver)
│   ├── dns_resolver.py        # 原生 RFC 1035 UDP 高并发 DNS 解析模块
│   ├── domains2ip.py          # 优选域名转 IP 业务编排与格式化引擎
│   ├── formatter.py           # VPS789 节点清洗与格式化引擎
│   ├── uouin.py               # UOUIN 麒麟优选逆向采集、Geo 增强与排序引擎
│   └── main.py                # 命令行统一入口
├── tests/
│   ├── __init__.py
│   ├── test_crypto.py         # 加解密与签名单元测试
│   ├── test_formatter.py      # 格式化规则全场景测试
│   ├── test_client.py         # API 客户端 Mock 测试
│   ├── test_uouin.py          # UOUIN 签名、过滤、Geo 与排序测试
│   └── test_domains2ip.py     # 域名转 IP 解析、指标继承与去重测试
└── .github/
    └── workflows/
        ├── crawl-domains.yml  # VPS789 优选域名与 domains2ip 联动采集工作流
        ├── crawl-bestip.yml   # VPS789 优选 IP 采集工作流
        └── crawl-uouin.yml    # UOUIN 麒麟优选 IP 采集工作流 (每 6 小时刷新)
```

---

## 四、 本地运行与测试

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 运行全部单元测试
```bash
python -m unittest discover tests
```

### 3. 本地执行采集

#### 方式一：使用独立麒麟优选脚本
```bash
# 采集麒麟优选 IP (默认筛选速度 >= 10.0mb/s，输出到根目录 uouin-bestip)
python -m crawler.uouin

# 自定义速度门限与输出路径
python -m crawler.uouin --min-speed 15.0 --output uouin-bestip

# 试运行（仅控制台输出预览，不写文件）
python -m crawler.uouin --dry-run
```

#### 方式二：使用统一入口命令行
```bash
# 仅采集麒麟优选 IP
python -m crawler.main --type uouin

# 采集 VPS789 优选域名（并自动联动生成 vps789-domains2ip）
python -m crawler.main --type domain

# 仅从已有的 vps789-domains 执行域名转 IP
python -m crawler.main --type domain2ip

# 仅采集 VPS789 优选 IP
python -m crawler.main --type ip --bestip-file vps789-bestip

# 全量全源采集 (更新 vps789-domains, vps789-domains2ip, vps789-bestip 与 uouin-bestip)
python -m crawler.main --type all
```

---

## 五、 GitHub Actions 自动化定时任务与部署

### 1. 定时器独立控制
本项目配置了三个完全独立的 GitHub Actions 工作流：
* **VPS789 优选域名与转IP** (`.github/workflows/crawl-domains.yml`)：每 24 小时运行，采集域名后无缝触发解析与 Geo 增强
* **VPS789 优选 IP** (`.github/workflows/crawl-bestip.yml`)：每 6 小时 30 分 (`30 */6 * * *`)
* **UOUIN 麒麟优选 IP** (`.github/workflows/crawl-uouin.yml`)：每 6 小时 45 分 (`45 */6 * * *`)

### 2. 手动触发与参数控制
在 GitHub 仓库 **Actions** 页面中，可随时选中任意工作流点击 **Run workflow** 手动触发：
* 支持自定义最低下载速度或过滤门限。
* 检测到文件内容产生变更时自动 commit & push；无变更时跳过提交，避免产生多余空提交。
