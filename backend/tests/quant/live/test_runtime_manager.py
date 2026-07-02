from __future__ import annotations

import asyncio

from quant.live.runtime_manager import RuntimeManager


class FakeRuntime:
    def __init__(self, tag: str, fail_on_start: bool = False) -> None:
        self.tag = tag
        self.fail_on_start = fail_on_start
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        if self.fail_on_start:
            raise RuntimeError("网关连接失败")
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


def test_reload_rebuilds_and_starts_new_runtime():
    builds: list[FakeRuntime] = []

    def build(live_state, params):
        rt = FakeRuntime(f"rt{len(builds)}")
        builds.append(rt)
        return rt

    manager = RuntimeManager(live_state=object(), params=object(), build=build)

    async def scenario():
        await manager.start()
        first = manager.runtime
        result = await manager.reload()
        return first, result

    first, result = asyncio.run(scenario())

    assert result == {"ok": True, "error": None}
    assert first.stopped is True            # 旧引擎已停
    assert manager.runtime is builds[-1]    # 当前是新建实例
    assert manager.runtime.started is True  # 新引擎已启动
    assert manager.runtime is not first


def test_reload_failure_stops_engine_and_reports_error():
    calls = {"n": 0}

    def build(live_state, params):
        calls["n"] += 1
        # 第一次(start)成功,第二次(reload)启动失败
        return FakeRuntime("rt", fail_on_start=calls["n"] >= 2)

    manager = RuntimeManager(live_state=object(), params=object(), build=build)

    async def scenario():
        await manager.start()
        return await manager.reload()

    result = asyncio.run(scenario())

    assert result["ok"] is False
    assert "网关连接失败" in result["error"]
    assert manager.runtime is None          # 安全停止态
    assert manager.last_error == "网关连接失败"


def test_start_failure_keeps_api_available_and_reports_error():
    def build(live_state, params):
        return FakeRuntime("rt", fail_on_start=True)

    manager = RuntimeManager(live_state=object(), params=object(), build=build)

    asyncio.run(manager.start())

    assert manager.runtime is None
    assert manager.last_error == "网关连接失败"


def test_concurrent_reloads_are_serialized():
    active = {"count": 0, "max": 0}

    class SlowRuntime(FakeRuntime):
        async def start(self) -> None:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            await asyncio.sleep(0.01)
            active["count"] -= 1
            self.started = True

    def build(live_state, params):
        return SlowRuntime("rt")

    manager = RuntimeManager(live_state=object(), params=object(), build=build)

    async def scenario():
        await manager.start()
        await asyncio.gather(manager.reload(), manager.reload(), manager.reload())

    asyncio.run(scenario())

    assert active["max"] == 1  # 任意时刻只有一个 reload 在跑
