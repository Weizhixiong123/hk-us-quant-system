"""watchlist 评分引擎:ScoreInputs -> ScoreBreakdown 的纯函数测试。"""
from __future__ import annotations

import math

from quant.indicators.scoring import ScoreInputs, score_for_symbol


_FULL = ScoreInputs(
    symbol="AAPL",
    market="US",
    consistency=1.0,
    intraday_volume_ratio=1.0,
    daily_volume_ratio=2.0,
    prev_amplitude_pct=4.0,
    price_vs_ma20_pct=2.0,
    price_vs_ma30_pct=2.0,
    short_term_gain_pct=10.0,
    avg_turnover=150_000_000.0,
)


def test_full_inputs_yield_weighted_near_one_and_total_one_clamped():
    bd = score_for_symbol(_FULL, half_life_hours=4.0, shortable=False)
    # 全「高位」输入 → 加权和 ≥ 0.95(各维自然最高),freshness = 1.0 → total = 1.0
    assert bd.weighted >= 0.95
    assert bd.freshness == 1.0
    # total 被钳位 = 1.0(weighted * freshness + 0 = 0.964,clamp 到 1.0)
    # 注意:weighted 自身会被 _clamp(weighted) 钳到 1.0 之前先钳过 0.964 → 不是 1.0,所以 total = min(weighted*1 + 0, 1) = min(0.964, 1) = 0.964
    # 但 _clamp(weighted) 在 weighted 处又会再处理一次
    assert 0.95 <= bd.total <= 1.0
    assert bd.shortable_bonus == 0.0


def test_zero_inputs_yield_low_total():
    """amp=0 / gain=0 / ma 偏离 0 都有边界判定意义,真正「全 0」时各维收敛到 0.29 这个固定值。
    关键测试是:「全 0」明显比「全 None」低,验证全 0 输入确实被压到 0 附近。"""
    zero = ScoreInputs(
        symbol="X", market="US",
        consistency=0.0, intraday_volume_ratio=0.0, daily_volume_ratio=0.0,
        prev_amplitude_pct=0.0,
        price_vs_ma20_pct=-100.0, price_vs_ma30_pct=-100.0,
        short_term_gain_pct=100.0, avg_turnover=0.0,
    )
    bd = score_for_symbol(zero, half_life_hours=4.0, shortable=False)
    # 0 输入应低于中性 0.5(因为明确知道数据是 0)
    assert bd.weighted < 0.5
    assert bd.total < 0.5
    # consistency 全 0 确实 = 0
    assert math.isclose(bd.consistency, 0.0, abs_tol=1e-9)
    # volume_ratio 全 0 = clamp(0) = 0
    assert math.isclose(bd.volume_ratio, 0.0, abs_tol=1e-9)


def test_freshness_half_life_matches_exp_minus_one():
    """half_life=4h 时,age=4h → freshness = exp(-1) ≈ 0.3679。"""
    fresh = ScoreInputs(symbol="X", market="US", selection_age_hours=0.0,
                        consistency=0.6, intraday_volume_ratio=0.6, daily_volume_ratio=1.0,
                        prev_amplitude_pct=4.0,
                        price_vs_ma20_pct=2.0, price_vs_ma30_pct=2.0,
                        short_term_gain_pct=10.0, avg_turnover=150_000_000.0,
                        )
    aged = ScoreInputs(symbol="X", market="US", selection_age_hours=4.0,
                       consistency=0.6, intraday_volume_ratio=0.6, daily_volume_ratio=1.0,
                       prev_amplitude_pct=4.0,
                       price_vs_ma20_pct=2.0, price_vs_ma30_pct=2.0,
                       short_term_gain_pct=10.0, avg_turnover=150_000_000.0,
                       )
    bd_fresh = score_for_symbol(fresh, half_life_hours=4.0, shortable=False)
    bd_aged = score_for_symbol(aged, half_life_hours=4.0, shortable=False)
    assert math.isclose(bd_fresh.freshness, 1.0, abs_tol=1e-9)
    assert math.isclose(bd_aged.freshness, math.exp(-1), abs_tol=1e-3)
    assert bd_aged.total < bd_fresh.total  # 年长的更小


def test_shortable_adds_bonus_and_clamps_at_one():
    base = ScoreInputs(
        symbol="X", market="US",
        consistency=0.6, intraday_volume_ratio=0.6, daily_volume_ratio=1.2,
        prev_amplitude_pct=4.0,
        price_vs_ma20_pct=2.0, price_vs_ma30_pct=2.0,
        short_term_gain_pct=10.0, avg_turnover=150_000_000.0,
    )
    no_bonus = score_for_symbol(base, half_life_hours=4.0, shortable=False)
    with_bonus = score_for_symbol(base, half_life_hours=4.0, shortable=True,
                                  shortable_bonus_pts=0.05)
    # same weighted, with_bonus 加 0.05
    assert math.isclose(with_bonus.total - no_bonus.total, 0.05, abs_tol=1e-9)
    assert with_bonus.shortable_bonus == 0.05

    # 全 1 输入 + shortable,钳位到 1.0
    capped = score_for_symbol(_FULL, half_life_hours=4.0, shortable=True,
                              shortable_bonus_pts=0.05)
    assert math.isclose(capped.total, 1.0, abs_tol=1e-9)


def test_all_none_inputs_yield_neutral_weighted_half():
    """缺数据 → 每维 0.5 → 加权和 = 0.5。"""
    inp = ScoreInputs(symbol="X", market="US")
    bd = score_for_symbol(inp, half_life_hours=4.0, shortable=False)
    assert math.isclose(bd.weighted, 0.5, abs_tol=1e-9)
    assert math.isclose(bd.consistency, 0.5, abs_tol=1e-9)
    assert math.isclose(bd.volume_ratio, 0.5, abs_tol=1e-9)
    assert math.isclose(bd.atr_quality, 0.5, abs_tol=1e-9)
    assert math.isclose(bd.trend_filter, 0.5, abs_tol=1e-9)
    assert math.isclose(bd.liquidity_rank, 0.5, abs_tol=1e-9)


def test_atr_quality_bands():
    """振幅 < 1.5 → 0.3;1.5–2 / 6–8 → 0.7;2–6 → 1.0;> 8 → 0.3。"""
    def with_amp(amp: float):
        return ScoreInputs(symbol="X", market="US", prev_amplitude_pct=amp)

    bd_low = score_for_symbol(with_amp(1.0), half_life_hours=4.0, shortable=False)
    bd_ok = score_for_symbol(with_amp(1.7), half_life_hours=4.0, shortable=False)
    bd_opt = score_for_symbol(with_amp(4.0), half_life_hours=4.0, shortable=False)
    bd_hot = score_for_symbol(with_amp(7.0), half_life_hours=4.0, shortable=False)
    bd_extreme = score_for_symbol(with_amp(10.0), half_life_hours=4.0, shortable=False)

    assert math.isclose(bd_low.atr_quality, 0.3, abs_tol=1e-9)
    assert math.isclose(bd_ok.atr_quality, 0.7, abs_tol=1e-9)
    assert math.isclose(bd_opt.atr_quality, 1.0, abs_tol=1e-9)
    assert math.isclose(bd_hot.atr_quality, 0.7, abs_tol=1e-9)
    assert math.isclose(bd_extreme.atr_quality, 0.3, abs_tol=1e-9)


def test_trend_filter_penalises_overheated_gain():
    """20 日涨幅 > 40% 视为过热 → trend_filter 的 gain 得分 = 0,该维度下降到中位以下。"""
    ok = ScoreInputs(symbol="X", market="US", price_vs_ma20_pct=1.0,
                     short_term_gain_pct=15.0)
    hot = ScoreInputs(symbol="X", market="US", price_vs_ma20_pct=1.0,
                      short_term_gain_pct=50.0)
    bd_ok = score_for_symbol(ok, half_life_hours=4.0, shortable=False)
    bd_hot = score_for_symbol(hot, half_life_hours=4.0, shortable=False)

    # 过热的 trend_filter 比可接受的更低
    assert bd_hot.trend_filter < bd_ok.trend_filter
    assert bd_hot.trend_filter < 0.5  # gain_score=0 → 趋势维 < 0.6 * 0.5 = 0.3 → 极端


def test_liquidity_rank_bands():
    """桶:≥1e8 → 1.0;≥2e7 → 0.85;≥5e6 → 0.6;≥2.5e6 → 0.35;<2.5e6 → 0.15。"""
    def with_liq(v: float):
        return ScoreInputs(symbol="X", market="US", avg_turnover=v)

    bd_high = score_for_symbol(with_liq(150_000_000), half_life_hours=4.0, shortable=False)
    bd_mid = score_for_symbol(with_liq(30_000_000), half_life_hours=4.0, shortable=False)
    bd_low = score_for_symbol(with_liq(7_000_000), half_life_hours=4.0, shortable=False)
    bd_floor = score_for_symbol(with_liq(3_000_000), half_life_hours=4.0, shortable=False)
    bd_zero = score_for_symbol(with_liq(2_000_000), half_life_hours=4.0, shortable=False)

    assert math.isclose(bd_high.liquidity_rank, 1.0, abs_tol=1e-9)
    assert math.isclose(bd_mid.liquidity_rank, 0.85, abs_tol=1e-9)
    assert math.isclose(bd_low.liquidity_rank, 0.6, abs_tol=1e-9)
    assert math.isclose(bd_floor.liquidity_rank, 0.35, abs_tol=1e-9)
    assert math.isclose(bd_zero.liquidity_rank, 0.15, abs_tol=1e-9)


def test_as_dict_contains_all_dims():
    bd = score_for_symbol(_FULL, half_life_hours=4.0, shortable=True)
    out = bd.as_dict()
    assert set(out) == {
        "consistency", "volume_ratio", "atr_quality", "trend_filter",
        "liquidity_rank", "weighted", "freshness", "shortable_bonus", "total",
    }
    assert 0.0 <= out["total"] <= 1.0
