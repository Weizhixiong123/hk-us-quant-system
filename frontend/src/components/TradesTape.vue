<script setup lang="ts">
import type { Trade } from "../api/types";

defineProps<{
  trades: Trade[];
}>();

function sideLabel(side: Trade["side"]): string {
  switch (side) {
    case "buy":
      return "买入";
    case "sell":
      return "卖出";
    case "short":
      return "卖空";
    case "cover":
      return "回补";
  }
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function money(value: number): string {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 0
  }).format(value);
}
</script>

<template>
  <div class="trades-tape">
    <div v-if="trades.length === 0" class="empty-inline">暂无成交回报</div>
    <article v-for="trade in trades.slice(0, 6)" :key="trade.id" class="trade-row">
      <time>{{ formatTime(trade.traded_at) }}</time>
      <strong>{{ trade.symbol }}</strong>
      <span>{{ sideLabel(trade.side) }}</span>
      <span>{{ money(trade.quantity) }} @ {{ trade.price.toFixed(2) }}</span>
    </article>
  </div>
</template>
