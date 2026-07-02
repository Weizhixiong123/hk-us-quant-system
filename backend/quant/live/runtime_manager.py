from __future__ import annotations

import asyncio
from typing import Any, Callable

from quant.live.runtime import build_live_runtime_from_env


class RuntimeManager:
    def __init__(
        self,
        live_state: Any,
        params: Any,
        build: Callable[[Any, Any], Any] = build_live_runtime_from_env,
    ) -> None:
        self._live_state = live_state
        self._params = params
        self._build = build
        self._runtime: Any | None = None
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    @property
    def runtime(self) -> Any | None:
        return self._runtime

    async def start(self) -> None:
        async with self._lock:
            try:
                await self._build_and_start()
                self.last_error = None
            except Exception as exc:
                self._runtime = None
                self.last_error = str(exc)

    async def stop(self) -> None:
        async with self._lock:
            if self._runtime is not None:
                await self._runtime.stop()
            self._runtime = None

    async def reload(self) -> dict:
        async with self._lock:
            if self._runtime is not None:
                await self._runtime.stop()
                self._runtime = None
            try:
                await self._build_and_start()
                self.last_error = None
                return {"ok": True, "error": None}
            except Exception as exc:  # 失败置停止态,不回滚
                self._runtime = None
                self.last_error = str(exc)
                return {"ok": False, "error": str(exc)}

    async def _build_and_start(self) -> None:
        runtime = self._build(self._live_state, self._params)
        await runtime.start()
        self._runtime = runtime
