<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const pageModules = import.meta.glob('../../../erp-compat/web/src/modules/**/*.vue')
const sessionModules = import.meta.glob('../../../erp-compat/web/src/stores/session.ts')
const sessionReady = ref(false)

const page = computed(() => {
  const modulePath = String(route.meta.erpCompatComponent || '')
  const loader = pageModules[modulePath]
  if (!loader) throw new Error(`Unknown ERP compatibility component: ${modulePath}`)
  return defineAsyncComponent(loader as () => Promise<{ default: object }>)
})

onMounted(async () => {
  try {
    const loader = Object.values(sessionModules)[0]
    if (!loader) return
    const module = await loader() as { useSessionStore?: () => { ready: boolean; restore: () => Promise<void> } }
    const session = module.useSessionStore?.()
    if (session && !session.ready) await session.restore()
  } finally {
    // Permission-aware ERP pages inspect the compatibility session during
    // their own onMounted hook, so they must not mount before restoration.
    sessionReady.value = true
  }
})
</script>

<template>
  <div class="erp-compat-page">
    <component v-if="sessionReady" :is="page" />
    <el-skeleton v-else :rows="8" animated />
  </div>
</template>
