"""Watchlist 候选可执行性综合分引擎。

5 维加权(consistency / volume_ratio / atr_quality / trend_filter / liquidity_rank),
外加 freshness 半衰期衰减和 shortable bonus。纯函数,无 I/O,无外部依赖。

约定:
    - 5 维每个输出范围 [0, 1](值越大越值得做)
    - 缺失的输入维度回落到 0.5(neutral),不会拉到 0
    - weighted = sum(dim * weight),范围 [0, 1]
    - freshness = exp(-age_hours / half_life_hours),age=None 或 half_life<=0 时为 1.0
    - total = min(weighted * freshness + shortable_bonus, 1.0)
    - score 字段为 0..1,前端会 `* 100` 取整数显示

替代方案 1(用户已选)。只暴露 `score_for_symbol()` 一个入口;`ScoreInputs` /
`ScoreBreakdown` 是 dataclass,方便测试断言也方便 `dataclasses.asdict` 持久化。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# 五维权重加起来 = 1.0
_WEIGHT_CONSISTENCY = 0.30
_WEIGHT_VOLUME_RATIO = 0.20
_WEIGHT_ATR_QUALITY = 0.15
_WEIGHT_TREND_FILTER = 0.20
_WEIGHT_LIQUIDITY_RANK = 0.15

# atr_quality 振幅分段(%) —— 与 quant/screening/intraday_screener.py:35 同步
_ATR_OPTIMAL = (2.0, 6.0)
_ATR_OK = (1.5, 8.0)

# liquidity 分桶 (USD / HKD 通用,数量级一致)
_LIQ_BAND_HIGH = 100_000_000.0
_LIQ_BAND_MID = 20_000_000.0
_LIQ_BAND_LOW = 5_000_000.0
_LIQ_BAND_FLOOR = _LIQ_BAND_LOW * 0.5  # 2.5M

# trend_filter 短期涨幅分界(%)
_TREND_GAIN_BLOCK = 40.0
_TREND_GAIN_PARTIAL = 20.0


@dataclass(frozen=True)
class ScoreInputs:
    """单只标的的评分输入,所有字段可为空(代表无该维度数据)。

    缺数据不等于零分,等于「不知道 → 给中性的 0.5」,保证旧事件不会因缺字段而
    永远比新事件低分(后者有数据 → 不再一律 0.5)。
    """

    symbol: str
    market: str
    # 三周期 MACD 一致度 passed_count / 3;运行时由 build_intraday_decision 写入
    consistency: float | None = None
    # 当日 5min vs 早盘 5min 量比(Band 内部);来自 BarAggregator
    intraday_volume_ratio: float | None = None
    # 当日成交量 / 20 日均量;来自 data_provider.daily_timing
    daily_volume_ratio: float | None = None
    # 昨日振幅 (%);来自 IntradayCandidate.prev_amplitude_pct
    prev_amplitude_pct: float | None = None
    # 收盘相对 MA20 的偏离度(%)signed
    price_vs_ma20_pct: float | None = None
    # 收盘相对 MA30 的偏离度(%)signed
    price_vs_ma30_pct: float | None = None
    # 20 日涨幅(%)signed;超过 _TREND_GAIN_BLOCK 视为过热
    short_term_gain_pct: float | None = None
    # 20 日均成交额(USD/HKD 一致量级);用于流动性分桶
    avg_turnover: float | None = None
    # selection event 距今的小时数;None 表示新鲜
    selection_age_hours: float | None = None


@dataclass(frozen=True)
class ScoreBreakdown:
    """单只标的评分输出。前端取 `total * 100` 显示整数,`as_dict()` 给 tooltip。"""

    consistency: float
    volume_ratio: float
    atr_quality: float
    trend_filter: float
    liquidity_rank: float
    weighted: float          # 加权和,freshness 之前
    freshness: float         # exp 衰减
    shortable_bonus: float   # 0 或 bonus_pts
    total: float             # 最终写入 WatchSymbol.score,范围 0..1

    def as_dict(self) -> dict[str, float]:
        return {
            "consistency": round(self.consistency, 4),
            "volume_ratio": round(self.volume_ratio, 4),
            "atr_quality": round(self.atr_quality, 4),
            "trend_filter": round(self.trend_filter, 4),
            "liquidity_rank": round(self.liquidity_rank, 4),
            "weighted": round(self.weighted, 4),
            "freshness": round(self.freshness, 4),
            "shortable_bonus": round(self.shortable_bonus, 4),
            "total": round(self.total, 4),
        }


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _or_neutral(value: float | None) -> float:
    """缺失输入 → 0.5(中性),不是 0。"""
    if value is None:
        return 0.5
    return _clamp(float(value))


def _consistency(inp: ScoreInputs) -> float:
    return _or_neutral(inp.consistency)


def _volume_ratio(inp: ScoreInputs) -> float:
    """70% intraday 量比 + 30% 日线量比。有则用,缺则忽略,最后平均。"""
    parts: list[float] = []
    intraday = inp.intraday_volume_ratio
    if intraday is not None and intraday >= 0:
        parts.append(_clamp(intraday))
    daily = inp.daily_volume_ratio
    if daily is not None and daily > 0:
        # daily_volume_ratio=2 表示 2 倍均量,满分
        parts.append(_clamp(daily / 2.0))
    if not parts:
        return 0.5
    return sum(parts) / len(parts)


def _atr_quality(inp: ScoreInputs) -> float:
    """振幅在 2-6% 视为最适合日内 MACD;过死或过激都降权。"""
    amp = inp.prev_amplitude_pct
    if amp is None or amp <= 0:
        return 0.5
    if _ATR_OPTIMAL[0] <= amp <= _ATR_OPTIMAL[1]:
        return 1.0
    if _ATR_OK[0] <= amp < _ATR_OPTIMAL[0] or _ATR_OPTIMAL[1] < amp <= _ATR_OK[1]:
        return 0.7
    return 0.3


def _trend_filter(inp: ScoreInputs) -> float:
    # 站上 MA20/30 的程度:偏离 -5% → 0, +5% → 1
    above_scores: list[float] = []
    for ma_dist in (inp.price_vs_ma20_pct, inp.price_vs_ma30_pct):
        if ma_dist is None:
            continue
        above_scores.append(_clamp((ma_dist + 5.0) / 10.0))
    above = sum(above_scores) / len(above_scores) if above_scores else 0.5

    # 短期涨幅:过热直接判 0
    gain = inp.short_term_gain_pct
    if gain is None:
        gain_score = 0.5
    elif gain <= _TREND_GAIN_PARTIAL:
        gain_score = 1.0
    elif gain <= _TREND_GAIN_BLOCK:
        gain_score = 0.6
    else:
        gain_score = 0.0

    return 0.6 * above + 0.4 * gain_score


def _liquidity_rank(inp: ScoreInputs) -> float:
    turnover = inp.avg_turnover
    if turnover is None or turnover <= 0:
        return 0.5
    if turnover >= _LIQ_BAND_HIGH:
        return 1.0
    if turnover >= _LIQ_BAND_MID:
        return 0.85
    if turnover >= _LIQ_BAND_LOW:
        return 0.6
    if turnover >= _LIQ_BAND_FLOOR:
        return 0.35
    return 0.15


def _freshness(age_hours: float | None, half_life_hours: float) -> float:
    if age_hours is None or age_hours < 0 or half_life_hours <= 0:
        return 1.0
    return math.exp(-age_hours / half_life_hours)


def score_for_symbol(
    inp: ScoreInputs,
    *,
    half_life_hours: float,
    shortable: bool,
    shortable_bonus_pts: float = 0.05,
) -> ScoreBreakdown:
    """给单个标的算一次评分。Pure function:同一个输入同一个输出。"""
    consistency = _consistency(inp)
    volume_ratio = _volume_ratio(inp)
    atr_quality = _atr_quality(inp)
    trend_filter = _trend_filter(inp)
    liquidity_rank = _liquidity_rank(inp)

    weighted = (
        _WEIGHT_CONSISTENCY * consistency
        + _WEIGHT_VOLUME_RATIO * volume_ratio
        + _WEIGHT_ATR_QUALITY * atr_quality
        + _WEIGHT_TREND_FILTER * trend_filter
        + _WEIGHT_LIQUIDITY_RANK * liquidity_rank
    )
    weighted = _clamp(weighted)

    freshness = _freshness(inp.selection_age_hours, half_life_hours)
    bonus = shortable_bonus_pts if shortable else 0.0
    total = _clamp(weighted * freshness + bonus)

    return ScoreBreakdown(
        consistency=consistency,
        volume_ratio=volume_ratio,
        atr_quality=atr_quality,
        trend_filter=trend_filter,
        liquidity_rank=liquidity_rank,
        weighted=weighted,
        freshness=freshness,
        shortable_bonus=bonus,
        total=total,
    )
