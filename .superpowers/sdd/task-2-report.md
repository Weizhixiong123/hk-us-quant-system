# Task 2 完成报告：历史数据加载器(可注入,不联网测试)

## 实现概述
Task 2 实现了数据加载层,负责将券商/免费数据源的原始 K 线标准化为统一的 OHLCV DataFrame。
核心特性:
- 通过依赖注入支持可插拔的数据源 (Fetcher)
- 自动列名标准化 (Open/Close → open/close)
- 数据清洗 (排序、删除 NaN 行)
- 两个内置数据源 (yfinance for US, akshare for HK)
- 测试环境通过注入 stub fetcher 实现不联网测试

## 创建/修改的文件

### 创建文件 1: `backend/quant/data/loaders.py`
- **位置**: `/www/hk-us-quant-system/backend/quant/data/loaders.py`
- **大小**: 53 行代码
- **核心内容**:
  - `Fetcher` 类型别名: 定义数据源接口 `Callable[[str, str, str, str], pd.DataFrame]`
  - `_COLUMN_ALIASES` 字典: 处理多种列名别名 (Open, open, Adj Close 等 → open/close)
  - `_default_fetcher()`: 内置数据源实现,支持 US (yfinance) 和 HK (akshare) 两个市场
  - `load_daily()`: 主入口函数,接受可选 fetcher 参数,执行标准化和清洗逻辑

### 创建文件 2: `backend/tests/quant/test_loaders.py`
- **位置**: `/www/hk-us-quant-system/backend/tests/quant/test_loaders.py`
- **大小**: 43 行代码
- **测试用例**:
  - `test_load_daily_normalizes_and_sorts()`: 验证列名标准化、排序、NaN 删除
  - `test_load_daily_passes_args_to_fetcher()`: 验证参数正确传递给 fetcher

## 测试命令与完整输出

### 运行 Task 2 专用测试
```bash
cd /www/hk-us-quant-system/backend && ./.venv/bin/python -m pytest tests/quant/test_loaders.py -v
```

**输出**:
```
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.1.1, pluggy-1.6.0 -- /www/hk-us-quant-system/backend/.venv/bin/python
cachedir: .pytest_cache
rootdir: /www/hk-us-quant-system/backend
collecting ... collected 2 items

tests/quant/test_loaders.py::test_load_daily_normalizes_and_sorts PASSED [ 50%]
tests/quant/test_loaders.py::test_load_daily_passes_args_to_fetcher PASSED [100%]

============================== 2 passed in 0.64s ===============================
```

### 完整测试套件验证 (无回归)
```bash
cd /www/hk-us-quant-system/backend && ./.venv/bin/python -m pytest -q
```

**输出**:
```
..........                                                               [100%]
10 passed in 0.79s
```

结论: 所有 10 项测试通过 (2 个新增 Task 2 测试 + 8 个现存测试), 无破坏现有功能。

## 自查发现

### 1. 标准化逻辑正确性
- 列名重映射: 通过 `_COLUMN_ALIASES` 字典处理所有上游数据源的列名变体 (yfinance 返回 Open/High/Low/Close/Volume, akshare 返回小写)
- 索引排序: 测试用 stub_fetch 故意使用乱序索引 [2024-01-03, 2024-01-02, 2024-01-04], 实现正确排序为递增顺序
- NaN 清洗: `dropna(subset=["close"])` 正确删除收盘价为 NaN 的行,保留其他完整行

### 2. 依赖注入设计
- `fetcher` 参数正确默认为 None, 使用 `fetcher or _default_fetcher` 模式
- 测试注入 `_stub_fetch()` 验证调用链路完整, stub 返回的数据经过完整标准化流程

### 3. 数据完整性
- `_REQUIRED` 列表定义必需 5 个列 (open/high/low/close/volume)
- 缺失列时抛出 ValueError, 防止下游处理异常
- 测试断言验证返回列顺序: `["open", "high", "low", "close", "volume"]`

### 4. 内置数据源兼容性
- US 市场: yfinance.download() 返回 DatetimeIndex, 列名为 Open/High/Low/Close/Volume/Adj Close, 通过别名映射处理
- HK 市场: akshare.stock_hk_daily() 返回含 date 列的 DataFrame, 需重命名为 Date 并设为索引, 再映射列名
- 两个数据源都通过 `pd.to_datetime()` 确保索引为 DatetimeIndex

### 5. TDD 流程遵循
- Step 1: 创建失败测试 ✓ (ModuleNotFoundError)
- Step 2: 确认失败 ✓
- Step 3: 最小实现 ✓ (逐字按简报代码)
- Step 4: 确认通过 ✓ (2 passed)
- Step 5: 提交 ✓ (commit hash: 11126076df4f27c4ab92f558d339aa1d253cedaa)

## 遗留疑虑

### 无已知风险
- 实现完全按简报规范编写, 无偏差
- 测试完整覆盖标准化、排序、清洗、参数传递四个关键路径
- yfinance/akshare 的惰性 import 在 `_default_fetcher()` 内部, 测试用 stub 不触发实际网络调用
- 虚拟环境已预装 pytest/pandas/numpy, yfinance/akshare 在单元测试中不需要 (inject fetcher)

### 设计考虑
- 返回 DataFrame 的列顺序统一为 ["open", "high", "low", "close", "volume"], 供后续重采样/选股使用
- DatetimeIndex 递增序确保后续时间序列操作正确性
- NaN 删除仅针对 close 列 (最关键), 不删除其他列的 NaN, 允许后续处理决定如何处理

## 提交信息
```
commit 11126076df4f27c4ab92f558d339aa1d253cedaa
Author: root <root@ser125102818807.local>
Date:   Sun Jun 22 15:46:00 2026 +0000

    feat(quant): 历史数据加载器(可注入数据源)
    
    创建:
    - backend/quant/data/loaders.py: 数据加载与标准化模块
    - backend/tests/quant/test_loaders.py: 单元测试 (2 passed)
    
    - Fetcher 类型别名支持可插拔数据源
    - load_daily() 标准化 OHLCV 列名 + 排序 + NaN 清洗
    - 内置 US (yfinance) / HK (akshare) 数据源
    - 依赖注入隔离,单元测试不联网
```

## 验证清单
- [x] 测试: `test_load_daily_normalizes_and_sorts` PASSED
- [x] 测试: `test_load_daily_passes_args_to_fetcher` PASSED
- [x] 全套测试: 10 passed (无回归)
- [x] 代码: 逐字按简报实现
- [x] TDD: 失败 → 通过 → 提交
- [x] Git: 分支 feature/backtest-first, 提交成功

---

## Fix: 重复close列

### 缺陷描述

`yfinance` 默认参数（`auto_adjust=False`）对美股同时返回 `Close` 和 `Adj Close` 两列；`_COLUMN_ALIASES` 将两者都映射为 `"close"`，`rename` 后产生重复的 `close` 列，导致 `df.dropna(subset=["close"])` 在 pandas 下抛 `InvalidIndexError`（或产生含两个 close 列的错误结果）。即 `_default_fetcher("AAPL","US",...)` 美股路径必崩。

### 改动说明

**文件 1: `backend/quant/data/loaders.py`**

两处修复：

1. **数据源层**（第 23 行）：`_default_fetcher` 美股分支加 `auto_adjust=True`，yfinance 不再返回 `Adj Close`，`Close` 即复权价：
   ```python
   return yf.download(symbol, start=start, end=end, interval="1d", progress=False, auto_adjust=True)
   ```

2. **标准化层防御**（第 47 行）：在 rename 之后、选列之前，去除重复列名，保留每个名字的第一列：
   ```python
   df = df.loc[:, ~df.columns.duplicated()]
   ```

3. **清理 `_COLUMN_ALIASES`**：移除五条无作用的恒等映射（`"open":"open"` 等），只保留真正的别名（`Open→open`、`Adj Close→close` 等），减少噪音。

**文件 2: `backend/tests/quant/test_loaders.py`**

新增回归测试 `test_load_daily_deduplicates_close_column`：注入一个同时含 `Close` 与 `Adj Close` 两列的 stub fetcher，断言：
- `load_daily` 不抛异常
- 结果中 `close` 列恰好只有一个（`list(df.columns).count("close") == 1`）
- 列集合等于标准五列（`set(df.columns) == {"open","high","low","close","volume"}`）
- 列顺序正确（`list(df.columns) == ["open","high","low","close","volume"]`）

### 测试命令与完整输出

#### TDD Step 1: 新增测试，先确认失败（复现崩溃）

```bash
cd /www/hk-us-quant-system/backend && ./.venv/bin/python -m pytest tests/quant/test_loaders.py -v
```

**输出（修复前）**：
```
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.1.1, pluggy-1.6.0
collected 3 items

tests/quant/test_loaders.py::test_load_daily_normalizes_and_sorts PASSED [ 33%]
tests/quant/test_loaders.py::test_load_daily_passes_args_to_fetcher PASSED [ 66%]
tests/quant/test_loaders.py::test_load_daily_deduplicates_close_column FAILED [100%]

FAILED tests/quant/test_loaders.py::test_load_daily_deduplicates_close_column
AssertionError: assert 2 == 1
  where 2 = list(['open', 'high', 'low', 'close', 'close', 'volume']).count('close')

========================= 1 failed, 2 passed in 0.97s =========================
```

#### TDD Step 2: 实施修复，确认全部通过

```bash
cd /www/hk-us-quant-system/backend && ./.venv/bin/python -m pytest tests/quant/test_loaders.py -v
```

**输出（修复后）**：
```
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.1.1, pluggy-1.6.0
collected 3 items

tests/quant/test_loaders.py::test_load_daily_normalizes_and_sorts PASSED [ 33%]
tests/quant/test_loaders.py::test_load_daily_passes_args_to_fetcher PASSED [ 66%]
tests/quant/test_loaders.py::test_load_daily_deduplicates_close_column PASSED [100%]

============================= 3 passed in 0.74s ===============================
```

#### TDD Step 3: 全套回归（无回归）

```bash
cd /www/hk-us-quant-system/backend && ./.venv/bin/python -m pytest -q
```

**输出**：
```
...........                                                              [100%]
11 passed in 0.75s
```

### 验证清单
- [x] 回归测试先失败（复现 Bug）
- [x] 修复后回归测试通过
- [x] 全套 11 项测试通过（无回归）
- [x] 数据源层修复：`auto_adjust=True`
- [x] 标准化层防御：`df.loc[:, ~df.columns.duplicated()]`
- [x] `_COLUMN_ALIASES` 去除噪音恒等映射

---

## Fix: MultiIndex列与缺失行契约

### 缺陷描述

**Important 缺陷（yfinance MultiIndex 列）**：现代 yfinance（≥0.2.51）即使单标的也返回二级列索引，如 `('Close','AAPL')`。原有 `df.rename(columns=_COLUMN_ALIASES)` 用字符串键无法匹配元组列，rename 形同空操作，后续 `dropna(subset=["close"])` 因找不到列名 `"close"` 抛 `KeyError`，美股真实路径会崩。

**Minor 契约缺口（无缺失行）**：绑定约束要求统一 OHLCV "无缺失行"，但原有 `dropna(subset=["close"])` 只检查 close 字段；volume 为 NaN 的行不会被剔除，违背契约。

### 改动说明

**文件 1: `backend/quant/data/loaders.py`**

三处修改：

1. **数据源层**（第 23 行）：`_default_fetcher` 美股分支加 `multi_level_index=False` 参数，让 yfinance 直接返回单级列名：
   ```python
   return yf.download(..., auto_adjust=True, multi_level_index=False)
   ```

2. **标准化层防御**（第 45-48 行）：在 `rename` 之前，若 `df.columns` 是 `pd.MultiIndex`，拍平为第 0 级，使任意数据源传入 MultiIndex 都能正确标准化：
   ```python
   if isinstance(raw.columns, pd.MultiIndex):
       raw = raw.copy()
       raw.columns = raw.columns.get_level_values(0)
   ```

3. **完善缺失行剔除**（第 58 行）：将 `dropna(subset=["close"])` 改为覆盖全部 OHLCV 字段：
   ```python
   df = df.dropna(subset=["open", "high", "low", "close", "volume"])
   ```

**文件 2: `backend/tests/quant/test_loaders.py`**

新增两项回归测试：

- **测试 A** `test_load_daily_flattens_multiindex_columns`：注入返回 `pd.MultiIndex.from_tuples([("Open","AAPL"),("High","AAPL"),("Low","AAPL"),("Close","AAPL"),("Volume","AAPL")])` 的 stub fetcher，断言不抛异常且输出列恰为 `["open","high","low","close","volume"]`。
- **测试 B** `test_load_daily_drops_row_with_volume_nan`：注入某行 `volume` 为 NaN（close 正常）的 stub，断言该行被剔除（`len(df)==2`）且剩余行 volume 均非空。

### 测试命令与完整输出

#### TDD Step 1: 新增测试，先确认失败（复现缺陷）

```bash
cd /www/hk-us-quant-system/backend && ./.venv/bin/python -m pytest tests/quant/test_loaders.py -v
```

**输出（修复前）**：
```
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.1.1, pluggy-1.6.0 -- /www/hk-us-quant-system/backend/.venv/bin/python
cachedir: .pytest_cache
rootdir: /www/hk-us-quant-system/backend
collecting ... collected 5 items

tests/quant/test_loaders.py::test_load_daily_normalizes_and_sorts PASSED [ 20%]
tests/quant/test_loaders.py::test_load_daily_passes_args_to_fetcher PASSED [ 40%]
tests/quant/test_loaders.py::test_load_daily_deduplicates_close_column PASSED [ 60%]
tests/quant/test_loaders.py::test_load_daily_flattens_multiindex_columns FAILED [ 80%]
tests/quant/test_loaders.py::test_load_daily_drops_row_with_volume_nan FAILED [100%]

FAILED tests/quant/test_loaders.py::test_load_daily_flattens_multiindex_columns - KeyError: ['close']
FAILED tests/quant/test_loaders.py::test_load_daily_drops_row_with_volume_nan - AssertionError: assert 3 == 2

========================= 2 failed, 3 passed in 1.29s ==========================
```

#### TDD Step 2: 实施修复，确认全部通过

```bash
cd /www/hk-us-quant-system/backend && ./.venv/bin/python -m pytest tests/quant/test_loaders.py -v
```

**输出（修复后）**：
```
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.1.1, pluggy-1.6.0 -- /www/hk-us-quant-system/backend/.venv/bin/python
cachedir: .pytest_cache
rootdir: /www/hk-us-quant-system/backend
collecting ... collected 5 items

tests/quant/test_loaders.py::test_load_daily_normalizes_and_sorts PASSED [ 20%]
tests/quant/test_loaders.py::test_load_daily_passes_args_to_fetcher PASSED [ 40%]
tests/quant/test_loaders.py::test_load_daily_deduplicates_close_column PASSED [ 60%]
tests/quant/test_loaders.py::test_load_daily_flattens_multiindex_columns PASSED [ 80%]
tests/quant/test_loaders.py::test_load_daily_drops_row_with_volume_nan PASSED [100%]

============================== 5 passed in 0.70s ===============================
```

#### TDD Step 3: 全套回归（无回归）

```bash
cd /www/hk-us-quant-system/backend && ./.venv/bin/python -m pytest -q
```

**输出**：
```
...........................                                              [100%]
27 passed in 0.96s
```

### 验证清单
- [x] 测试 A 先失败（复现 MultiIndex KeyError）
- [x] 测试 B 先失败（volume NaN 行未被剔除）
- [x] 数据源层修复：`multi_level_index=False`
- [x] 标准化层防御：`get_level_values(0)` 拍平 MultiIndex
- [x] 缺失行契约完善：`dropna` 覆盖全部 OHLCV 字段
- [x] 修复后 5 项 loader 测试全部通过
- [x] 全套 27 项测试通过（无回归）
