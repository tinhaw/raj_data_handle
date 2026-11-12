<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import AppShell from './components/AppShell.vue'
import ThemeToggle from './components/ThemeToggle.vue'

const route = useRoute()
const blankLayout = computed(() => route.meta.layout === 'blank')
</script>

<template>
  <div v-if="blankLayout" class="login-theme-control"><ThemeToggle /></div>
  <router-view v-if="blankLayout" />
  <AppShell v-else />
</template>

<style scoped>
.login-theme-control {
  position: fixed;
  top: 20px;
  right: 24px;
  z-index: 100;
}
</style>
