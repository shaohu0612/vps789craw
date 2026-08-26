# VPS789 Cloudflare 优选节点采集与自动发布系统

本项目用于自动化定时采集 [vps789.com](https://vps789.com) 的 Cloudflare 优选节点（包含优选域名与优选 IP），经过规范化格式清洗与去重后，自动提交发布至 GitHub 仓库 `shaohu0612/vps789craw` 的 `main` 分支。

---

## 一、 输出地址与订阅链接

* **优选域名列表**：
  `https://raw.githubusercontent.com/shaohu0612/vps789craw/refs/heads/main/vps789-domains`
* **优选 IP 列表**：
  `https://raw.githubusercontent.com/shaohu0612/vps789craw/refs/heads/main/vps789-bestip`

---

## 二、 格式化与清洗规则

输出格式统一为：`CF优选IP:端口#前缀-备注`（默认前缀为 `vps789-`）

| 采集源 | 条件分支 | 格式化输出示例 | 说明 |
| :--- | :--- | :--- | :--- |
| **优选域名** (`remarks=domain`) | 域名且端口为 `443` | `www.shopify.com#vps789-www.shopify.com` | 443 端口省略；前缀为 `vps789-`；备注为空则复用域名 |
| **优选域名** (`remarks=domain`) | 域名且端口为 `443`，有备注 | `dnew.cc#vps789-yong` | 443 端口省略；拼接前缀 `vps789-` 与备注 `yong` |
| **优选域名** (`remarks=domain`) | 域名且端口不为 `443` | `cdn.test.com:8443#vps789-cdn.test.com` | 保留 `:端口`；前缀为 `vps789-` |
| **优选域名** (`remarks=domain`) | 若节点为 IP 地址 | `104.21.20.210:443#vps789-104.21.20.210` | 若为 IP 地址，`:端口` 绝不可省略 |
| **优选 IP** (`remarks=ip`) | IP 地址且端口为 `443` | `172.67.212.221:443#vps789-172.67.212.221` | `:端口` 绝不可省略；前缀为 `vps789-`；备注为空则复用 IP |

---

## 三、 项目架构

```
vps789craw/
├── AGENTS.md                  # 全局 Agent 指导与开发规范
├── README.md                  # 项目说明与部署指南
├── requirements.txt           # Python 依赖声明
├── .env.example               # 环境变量配置示例
├── vps789-domains             # 优选域名最新输出文件
├── vps789-bestip              # 优选 IP 最新输出文件
├── crawler/
│   ├── __init__.py
│   ├── crypto.py              # VPS789 动态 DES-CBC 加解密与鉴权 Token 生成
│   ├── client.py              # API 交互客户端（自动重试、分页拉取与解密）
│   ├── formatter.py           # 节点数据清洗、校验与格式化引擎
│   └── main.py                # 命令行主入口
├── tests/
│   ├── __init__.py
│   ├── test_crypto.py         # 加解密与签名单元测试
│   ├── test_formatter.py      # 格式化规则全场景测试
│   └── test_client.py         # API 客户端 Mock 测试
└── .github/
    └── workflows/
        ├── crawl-domains.yml  # 独立控制的优选域名采集工作流
        └── crawl-bestip.yml   # 独立控制的优选 IP 采集工作流
```

---

## 四、 本地运行与测试

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 运行全部单元测试
```bash
pytest -v
```

### 3. 本地执行采集
```bash
# 全量采集（同时生成 vps789-domains 与 vps789-bestip）
python -m crawler.main --type all

# 仅采集优选域名
python -m crawler.main --type domain --domains-file vps789-domains

# 仅采集优选 IP
python -m crawler.main --type ip --bestip-file vps789-bestip

# 试运行（仅控制台输出预览，不写文件）
python -m crawler.main --type all --dry-run
```

---

## 五、 GitHub Actions 部署到 `shaohu0612/vps789craw` 仓库

### 1. 部署代码至仓库
将本项目的所有文件提交并推送到 GitHub 仓库 `shaohu0612/vps789craw` 的 `main` 分支：
```bash
git init
git add .
git commit -m "feat: 初始化 vps789 优选节点采集与定时同步系统"
git remote add origin https://github.com/shaohu0612/vps789craw.git
git push -u origin main
```

### 2. 配置 GitHub Actions 权限与 Secrets
1. **开启 Actions 写入权限**：
   * 进入仓库 `shaohu0612/vps789craw` -> **Settings** -> **Actions** -> **General**。
   * 在 **Workflow permissions** 中选择 **Read and write permissions** 并保存。
2. **配置 Personal Access Token (可选 / 推荐)**：
   * 若使用个人访问令牌（PAT），请在 GitHub 生成包含 `repo` 和 `workflow` 权限的 Token。
   * 进入仓库 **Settings** -> **Secrets and variables** -> **Actions**。
   * 新增 Secret：名称为 `GH_PAT`，值为生成的 Token。
   * 若未配置 `GH_PAT`，工作流将自动回退使用系统默认的 `GITHUB_TOKEN`。

### 3. 定时器独立控制与启用/停用
* **独立定时器**：
  * 域名采集 (`.github/workflows/crawl-domains.yml`)：默认每 6 小时整点运行 (`0 */6 * * *`)。
  * IP 采集 (`.github/workflows/crawl-bestip.yml`)：默认每 6 小时 30 分运行 (`30 */6 * * *`)。
* **控制台手动触发与停用开关**：
  * 进入仓库 **Actions** 标签页。
  * 选择 **VPS789 Crawl Domains** 或 **VPS789 Crawl Best IP**。
  * 点击 **Run workflow**，可通过下拉勾选框选择是否启用该次采集。
  * 如需临时停用某一任务的定时调度，可以在 GitHub 仓库 Actions 列表中点击 `...` -> **Disable workflow**。
