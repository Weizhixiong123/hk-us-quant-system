<script setup lang="ts">
import type { Position } from "../api/types";

defineProps<{
  positions: Position[];
}>();

function money(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 0
  }).format(value);
}
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>标的</th>
          <th>策略</th>
          <th>方向</th>
          <th>数量</th>
          <th>现价</th>
          <th>市值</th>
          <th>盈亏</th>
          <th>持仓天数</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="position in positions" :key="position.symbol">
          <td>
            <strong>{{ position.symbol }}</strong>
            <small>{{ position.name }}</small>
          </td>
          <td>{{ position.strategy_id }}</td>
          <td>{{ position.side === "long" ? "多" : "空" }}</td>
          <td>{{ money(position.quantity) }}</td>
          <td>{{ position.last_price.toFixed(2) }}</td>
          <td>{{ money(position.market_value) }}</td>
          <td :class="position.pnl >= 0 ? 'gain' : 'loss'">
            {{ money(position.pnl) }} / {{ position.pnl_pct.toFixed(2) }}%
          </td>
          <td>{{ position.holding_days }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

