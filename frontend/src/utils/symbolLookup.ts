import type { Market } from "../api/types";

/**
 * 常用标的 → 中文/英文名称本地映射。
 * 用于手动股票池「输入代码自动回填名称」的快速路径。
 *
 * 设计原则:
 *  - 常用 US 蓝筹/ETF + HK 蓝筹/指数优先本地命中
 *  - 代码用归一化 key(US:大写无后缀 / HK:5 位数字无后缀),与 ManualUniversePanel.normalizeSymbol 输出对齐
 *  - 查不到时返回 null,由调用方继续查询后端行情源
 */

/** US 用大写字符串作为 key(避免数字被解析成八进制) */
const US_SYMBOLS: Record<string, string> = {
  // --- mega cap tech ---
  AAPL: "苹果",
  MSFT: "微软",
  GOOGL: "谷歌 A",
  GOOG: "谷歌 C",
  AMZN: "亚马逊",
  META: "Meta",
  NVDA: "英伟达",
  TSLA: "特斯拉",
  NFLX: "奈飞",
  ORCL: "甲骨文",
  CRM: "Salesforce",
  ADBE: "Adobe",
  INTC: "英特尔",
  AMD: "AMD",
  QCOM: "高通",
  AVGO: "博通",
  ASML: "阿斯麦",
  MU: "美光",
  IBM: "IBM",
  CSCO: "思科",

  // --- consumer / retail ---
  WMT: "沃尔玛",
  COST: "好市多",
  HD: "家得宝",
  MCD: "麦当劳",
  SBUX: "星巴克",
  NKE: "耐克",
  DIS: "迪士尼",
  KO: "可口可乐",
  PEP: "百事",
  PG: "宝洁",
  PM: "菲利普莫里斯",
  MO: "奥驰亚",
  UL: "联合利华",
  CL: "高露洁",

  // --- finance ---
  JPM: "摩根大通",
  BAC: "美国银行",
  WFC: "富国银行",
  C: "花旗",
  GS: "高盛",
  MS: "摩根士丹利",
  BLK: "贝莱德",
  BRK_B: "伯克希尔 B",
  V: "Visa",
  MA: "万事达",
  AXP: "美国运通",
  SPGI: "标普全球",

  // --- health ---
  UNH: "联合健康",
  JNJ: "强生",
  LLY: "礼来",
  PFE: "辉瑞",
  MRK: "默沙东",
  ABBV: "艾伯维",
  TMO: "赛默飞世尔",
  ABT: "雅培",
  DHR: "丹纳赫",
  BMY: "百时美施贵宝",

  // --- energy / industrial ---
  XOM: "埃克森美孚",
  CVX: "雪佛龙",
  COP: "康菲石油",
  SLB: "斯伦贝谢",
  BA: "波音",
  CAT: "卡特彼勒",
  GE: "通用电气",
  HON: "霍尼韦尔",
  UPS: "联合包裹",
  RTX: "RTX",

  // --- utilities / telecom ---
  T: "AT&T",
  VZ: "威瑞森",
  TMUS: "T-Mobile",
  NEE: "新纪元能源",
  SO: "南方公司",

  // --- China ADR ---
  BABA: "阿里巴巴",
  PDD: "拼多多",
  JD: "京东",
  BIDU: "百度",
  NIO: "蔚来",
  XPEV: "小鹏汽车",
  LI: "理想汽车",
  NTES: "网易",
  BILI: "哔哩哔哩",
  TME: "腾讯音乐",
  YUMC: "百胜中国",
  EDU: "新东方",
  TAL: "好未来",
  ZTO: "中通快递",
  BEKE: "贝壳",

  // --- popular ETFs ---
  SPY: "标普 500 ETF",
  QQQ: "纳斯达克 100 ETF",
  DIA: "道琼斯 ETF",
  IWM: "罗素 2000 ETF",
  VOO: "Vanguard 标普 500 ETF",
  VTI: "Vanguard 全市场 ETF",
  IWF: "罗素 1000 成长 ETF",
  IWD: "罗素 1000 价值 ETF",
  XLK: "科技精选 ETF",
  XLF: "金融精选 ETF",
  XLE: "能源精选 ETF",
  XLV: "医疗精选 ETF",
  XLY: "可选消费 ETF",
  XLP: "必需消费 ETF",
  ARKK: "ARK 创新 ETF",
  SOXX: "半导体 ETF",
  TLT: "长期国债 ETF",
  HYG: "高收益债 ETF",
  GLD: "黄金 ETF",
  SLV: "白银 ETF",
  USO: "原油 ETF",
  UVXY: "波动率 ETF",
  SQQQ: "纳指三倍做空",
  TQQQ: "纳指三倍做多",
  SPXU: "标普三倍做空",
  UPRO: "标普三倍做多",
  SH: "标普500反向 ETF"
};

/** HK 用 5 位零填充字符串作为 key —— 避免 `0700` 被解析成八进制,也跟归一化输出一致 */
const HK_SYMBOLS: Record<string, string> = {
  // --- 蓝筹 / 重磅 ---
  "00700": "腾讯控股",
  "09988": "阿里巴巴-W",
  "03690": "美团-W",
  "01810": "小米集团-W",
  "09618": "京东集团-SW",
  "09999": "网易-S",
  "09888": "百度集团-SW",
  "01024": "快手-W",
  "09626": "哔哩哔哩-W",
  "02382": "舜宇光学",

  // --- 金融 ---
  "00005": "汇丰控股",
  "00011": "恒生银行",
  "00388": "香港交易所",
  "00939": "建设银行",
  "01398": "工商银行",
  "03988": "中国银行",
  "02628": "中国人寿",
  "02318": "中国平安",
  "01299": "友邦保险",

  // --- 能源 / 资源 ---
  "00883": "中国海洋石油",
  "00857": "中国石油股份",
  "00386": "中国石油化工",
  "01088": "中国神华",
  "02899": "紫金矿业",
  "01818": "招金矿业",

  // --- 消费 / 出行 ---
  "09992": "泡泡玛特",
  "02020": "安踏体育",
  "00881": "中升控股",
  "00027": "银河娱乐",
  "01177": "中国生物制药",
  "02269": "药明生物",

  // --- 指数/ETF ---
  "02800": "盈富基金",
  "02828": "恒生中国企业 ETF",
  "07200": "南方两倍看多恒指",
  "07300": "南方两倍看空恒指",
  "07500": "恒指两倍做多 ETF",
  "07700": "恒指两倍做空 ETF",
  "05800": "盈富杠杆 ETF"
};

/** US 用大写无后缀,HK 用归一化的 5 位数字(归一化逻辑请参考 ManualUniversePanel.normalizeSymbol) */
export interface SymbolLookupResult {
  key: string;
  name: string | null;
}

/** 把用户输入归一化成查找 key:US → 大写无后缀 / HK → 5 位零填充 */
export function normalizeLookupKey(symbol: string, market: Market): string {
  const s = symbol.trim().toUpperCase().replace(/\s+/g, "");
  if (market === "US") {
    return s.replace(/\.US$/, "").replace(/[.-]/g, "_");
  }
  // HK:0700 / 700 / 00700 / 0700.HK 全部归一化成 5 位零填充字符串
  // 关键:先把所有非数字字符剥掉(去掉 .HK / HK. 前缀),再 padStart(5)
  // —— 用 5 位(不是 4 位)是为了跟"0700.HK"这种 4 位代码的前导 0 对齐
  const digits = s.replace(/[^0-9]/g, "");
  if (!/^\d+$/.test(digits)) return digits;
  return digits.padStart(5, "0");
}

export function lookupSymbolName(symbol: string, market: Market): string | null {
  if (!symbol) return null;
  const key = normalizeLookupKey(symbol, market);
  if (market === "US") {
    return US_SYMBOLS[key] ?? null;
  }
  return HK_SYMBOLS[key] ?? null;
}

/** 调试/测试用:返回当前映射规模 */
export function _lookupStats(): { us: number; hk: number } {
  return {
    us: Object.keys(US_SYMBOLS).length,
    hk: Object.keys(HK_SYMBOLS).length
  };
}
