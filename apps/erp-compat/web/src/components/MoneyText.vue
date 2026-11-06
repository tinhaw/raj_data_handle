<script setup lang="ts">
import { computed } from 'vue'
import { formatMoney, toDecimal } from '@/utils/money'

const props = withDefaults(defineProps<{ value?: string | number | null; digits?: number; colorize?: boolean }>(), {
  digits: 2,
  colorize: false,
})

const negative = computed(() => toDecimal(props.value).isNegative())
</script>

<template>
  <span class="money" :class="{ 'money--negative': colorize && negative, 'money--positive': colorize && !negative }">
    {{ formatMoney(value, digits) }}
  </span>
</template>
