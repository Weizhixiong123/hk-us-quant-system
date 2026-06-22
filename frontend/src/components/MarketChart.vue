<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  ColorType,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type Time
} from "lightweight-charts";
import type { Candle } from "../api/types";

const props = defineProps<{
  candles: Candle[];
}>();

const container = ref<HTMLDivElement | null>(null);
let chart: IChartApi | null = null;
let series: ISeriesApi<"Candlestick"> | null = null;
let observer: ResizeObserver | null = null;

function asTimestamp(time: string): Time {
  const [hour, minute] = time.split(":").map(Number);
  const date = new Date(Date.UTC(2026, 5, 22, hour || 0, minute || 0, 0));
  return Math.floor(date.getTime() / 1000) as Time;
}

function toChartData(candles: Candle[]): CandlestickData[] {
  // lightweight-charts requires strictly ascending times — dedupe by time, keeping last
  const seen = new Map<number, CandlestickData>();
  for (const candle of candles) {
    const ts = asTimestamp(candle.time);
    seen.set(ts, {
      time: ts,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close
    });
  }
  return Array.from(seen.values()).sort((a, b) => (a.time as number) - (b.time as number));
}

function render() {
  if (!series) {
    return;
  }
  series.setData(toChartData(props.candles));
  chart?.timeScale().fitContent();
}

onMounted(() => {
  if (!container.value) {
    return;
  }
  chart = createChart(container.value, {
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: "#4b5355",
      fontFamily: "Bahnschrift, Microsoft YaHei UI, sans-serif"
    },
    grid: {
      vertLines: { color: "rgba(33, 48, 49, 0.08)" },
      horzLines: { color: "rgba(33, 48, 49, 0.08)" }
    },
    width: container.value.clientWidth,
    height: 330,
    rightPriceScale: {
      borderColor: "rgba(33, 48, 49, 0.12)"
    },
    timeScale: {
      borderColor: "rgba(33, 48, 49, 0.12)",
      timeVisible: true,
      secondsVisible: false
    },
    crosshair: {
      vertLine: { color: "#16a394" },
      horzLine: { color: "#16a394" }
    }
  });
  series = chart.addCandlestickSeries({
    upColor: "#178f67",
    downColor: "#cf4a43",
    borderUpColor: "#178f67",
    borderDownColor: "#cf4a43",
    wickUpColor: "#178f67",
    wickDownColor: "#cf4a43"
  });
  render();
  observer = new ResizeObserver(([entry]) => {
    chart?.applyOptions({ width: Math.floor(entry.contentRect.width) });
  });
  observer.observe(container.value);
});

watch(
  () => props.candles,
  () => render(),
  { deep: true }
);

onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.remove();
});
</script>

<template>
  <div ref="container" class="chart-canvas" />
</template>

