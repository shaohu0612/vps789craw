"""
VPS789 采集与导出主入口 CLI
支持通过命令行参数分别或全量抓取域名与 IP 列表，并输出到目标文件。
"""

import argparse
import logging
import os
import sys
from typing import List, Optional

from crawler.client import VPS789Client
from crawler.formatter import format_node_list


def setup_logging(verbose: bool = False) -> None:
    """
    初始化日志记录器
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def process_crawl(
    client: VPS789Client,
    crawl_type: str,
    output_path: str,
    prefix: str = "vps789-",
    max_latency: Optional[float] = None,
    max_loss_rate: Optional[float] = None,
    dry_run: bool = False
) -> int:
    """
    执行单项采集任务并保存到指定文件。

    :param client: API 客户端
    :param crawl_type: 采集类型 "domain" 或 "ip"
    :param output_path: 输出文件完整路径
    :param prefix: 备注前缀，默认为 "vps789-"
    :param max_latency: 最大允许三网平均延迟 (ms)，None 表示不限制
    :param max_loss_rate: 最大允许三网平均丢包率 (%)，None 表示不限制
    :param dry_run: 是否为试运行模式（不写磁盘）
    :return: 抓取并格式化的有效行数
    """
    logger = logging.getLogger(__name__)
    filter_info = f" (质量过滤: 延迟<={max_latency}ms, 丢包率<={max_loss_rate}%)" if (max_latency is not None or max_loss_rate is not None) else ""
    logger.info(f"===> 开始处理采集任务: 类型=[{crawl_type}]{filter_info} -> 输出目标=[{output_path}]")

    raw_items = client.fetch_all(remarks_type=crawl_type)
    if not raw_items:
        logger.warning(f"未能获取到 [{crawl_type}] 任何数据，任务终止")
        return 0

    formatted_text = format_node_list(
        raw_items,
        prefix=prefix,
        deduplicate=True,
        max_latency=max_latency,
        max_loss_rate=max_loss_rate
    )
    lines_count = len(formatted_text.splitlines()) if formatted_text else 0

    logger.info(f"清洗与格式化完成: 原始 {len(raw_items)} 条 -> 过滤与去重后有效 {lines_count} 条")

    if dry_run:
        logger.info("[试运行模式] 不写入文件，前 10 行预览:")
        print("\n".join(formatted_text.splitlines()[:10]))
        return lines_count

    # 确保输出目录存在
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # 写入目标文件 (UTF-8 编码，保留标准换行)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(formatted_text + "\n")

    logger.info(f"成功保存到文件: {output_path} (共 {lines_count} 行)")
    return lines_count


def main(argv: List[str] = None) -> int:
    """
    主程序入口
    """
    parser = argparse.ArgumentParser(description="VPS789 Cloudflare 优选节点采集与格式化工具")
    parser.add_argument(
        "--type",
        choices=["domain", "ip", "all"],
        default="all",
        help="采集类型: domain (仅优选域名), ip (仅优选 IP), all (两者皆采集)"
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="输出文件所在目录，默认为当前工作目录"
    )
    parser.add_argument(
        "--domains-file",
        default="vps789-domains",
        help="优选域名输出文件名，默认为 vps789-domains"
    )
    parser.add_argument(
        "--bestip-file",
        default="vps789-bestip",
        help="优选 IP 输出文件名，默认为 vps789-bestip"
    )
    parser.add_argument(
        "--prefix",
        default="vps789-",
        help="节点备注前缀（插入在 # 与备注之间），默认为 vps789-"
    )
    parser.add_argument(
        "--max-latency",
        type=float,
        default=300.0,
        help="三网最大允许平均延迟（毫秒），默认 300.0ms（默认应用于优选域名）"
    )
    parser.add_argument(
        "--max-loss-rate",
        type=float,
        default=10.0,
        help="三网最大允许平均丢包率（百分比），默认 10.0%（默认应用于优选域名）"
    )
    parser.add_argument(
        "--filter-bestip",
        action="store_true",
        help="是否同时对优选 IP 进行三网延迟与丢包率质量过滤（默认不过滤，仅过滤优选域名）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式，仅在终端打印预览，不写入文件"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="启用详细 Debug 日志"
    )

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    client = VPS789Client()

    try:
        if args.type in ("domain", "all"):
            domains_path = os.path.join(args.output_dir, args.domains_file)
            process_crawl(
                client=client,
                crawl_type="domain",
                output_path=domains_path,
                prefix=args.prefix,
                max_latency=args.max_latency,
                max_loss_rate=args.max_loss_rate,
                dry_run=args.dry_run
            )

        if args.type in ("ip", "all"):
            bestip_path = os.path.join(args.output_dir, args.bestip_file)
            process_crawl(
                client=client,
                crawl_type="ip",
                output_path=bestip_path,
                prefix=args.prefix,
                max_latency=args.max_latency if args.filter_bestip else None,
                max_loss_rate=args.max_loss_rate if args.filter_bestip else None,
                dry_run=args.dry_run
            )

        logger.info("所有采集任务执行完毕！")
        return 0

    except Exception as e:
        logger.error(f"采集执行过程中发生未捕获异常: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
