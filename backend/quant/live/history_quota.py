from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def unpack_history_kline_quota(data: object) -> tuple[int, int, list[Mapping[str, Any]]]:
    if isinstance(data, Mapping):
        used = data.get("used_quota", 0)
        remaining = data.get("remain_quota", 0)
        details = data.get("detail_list", [])
    elif isinstance(data, (list, tuple)) and len(data) >= 3:
        used, remaining, details = data[:3]
    else:
        raise RuntimeError(f"无法识别富途历史K线额度返回格式：{type(data).__name__}")

    if not isinstance(details, (list, tuple)):
        raise RuntimeError("富途历史K线额度明细格式异常")
    normalized_details = [item for item in details if isinstance(item, Mapping)]
    return int(used), int(remaining), normalized_details
