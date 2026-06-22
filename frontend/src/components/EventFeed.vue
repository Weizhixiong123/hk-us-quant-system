<script setup lang="ts">
import { computed } from "vue";
import type { Signal, TradeLog } from "../api/types";

const props = defineProps<{
  signals: Signal[];
  logs: TradeLog[];
}>();

const events = computed(() => [
  ...props.signals.map((signal) => ({
    id: signal.id,
    time: signal.created_at,
    source: signal.strategy_id,
    tone: signal.status === "filtered" ? "warning" : "info",
    title: `${signal.symbol} · ${signal.side}`,
    message: signal.reason
  })),
  ...props.logs.map((log) => ({
    id: log.id,
    time: log.time,
    source: log.source,
    tone: log.severity,
    title: log.source,
    message: log.message
  }))
].sort((left, right) => Date.parse(right.time) - Date.parse(left.time)).slice(0, 8));

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
</script>

<template>
  <div class="event-feed">
    <article v-for="event in events" :key="event.id" class="event-row" :class="event.tone">
      <time>{{ formatTime(event.time) }}</time>
      <div>
        <strong>{{ event.title }}</strong>
        <p>{{ event.message }}</p>
      </div>
    </article>
  </div>
</template>

