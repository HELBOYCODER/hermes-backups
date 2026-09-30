"""
LightClaw (hermes) — 指标上报 HTTP 客户端

上报到 ai-server 的 /log/report。

内置 L1 短时抖动重试（指数退避 1s→3s→9s）。
重试耗尽仍失败时返回 False，调用方（collector.py）负责转入本地降级缓冲。
"""

import asyncio
import json
import logging
from typing import Dict, List

from ..config import (
    API_PATH_METRICS_REPORT,
    METRICS_REPORT_MAX_RETRIES,
    METRICS_REPORT_RETRY_BASE_DELAY,
    METRICS_REPORT_RETRY_FACTOR,
    METRICS_REPORT_TIMEOUT,
)

logger = logging.getLogger(__name__)


async def report_metrics_batch(
    api_base_url: str,
    aiohttp_session,          # aiohttp.ClientSession（复用 adapter 共享连接池）
    items: List[Dict],
    api_key: str,
) -> bool:
    """上报一批指标。

    :param api_base_url: 当前 site 的 API base url
    :param aiohttp_session: 复用的 aiohttp.ClientSession
    :param items: 待上报条目（对应 ai-server ``{ items: [...] }`` 请求体）
    :param api_key: 目标uin 的 apiKey（用于构建鉴权 header——务必使用该
        uin 自己的 apiKey，不能用其它 uin 的，否则 ai-server 侧会把这批
        指标错误归属到别的租户）
    :return: True = 服务端已接收（HTTP 2xx）；False = 重试耗尽仍失败
    """
    if not items:
        return True

    import aiohttp

    url = f"{api_base_url}{API_PATH_METRICS_REPORT}"
    headers = {"authorization": f"Bearer {api_key}", "x-product": "channel"}

    for attempt in range(METRICS_REPORT_MAX_RETRIES + 1):
        try:
            async with aiohttp_session.post(
                url, headers=headers, json={"items": items},
                timeout=aiohttp.ClientTimeout(total=METRICS_REPORT_TIMEOUT),
            ) as resp:
                if resp.status // 100 == 2:
                    logger.info(
                        "[metrics] report ok: items=%d payload=%s",
                        len(items), json.dumps(items, ensure_ascii=False),
                    )
                    return True
                logger.warning(
                    "[metrics] report HTTP %s, attempt=%d, items=%d",
                    resp.status, attempt, len(items),
                )
        except Exception as exc:
            logger.warning(
                "[metrics] report request failed: %s, attempt=%d, items=%d",
                exc, attempt, len(items),
            )

        if attempt < METRICS_REPORT_MAX_RETRIES:
            delay = METRICS_REPORT_RETRY_BASE_DELAY * (METRICS_REPORT_RETRY_FACTOR ** attempt)
            await asyncio.sleep(delay)

    return False
