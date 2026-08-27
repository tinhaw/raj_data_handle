<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const pageModules = import.meta.glob('../../../erp-compat/web/src/modules/**/*.vue')
const sessionModules = import.meta.glob('../../../erp-compat/web/src/stores/session.ts')

const page = computed(() => {
  const modulePath = String(route.meta.erpCompatComponent || '')
  const loader = pageModules[modulePath]
  if (!loader) throw new Error(`Unknown ERP compatibility component: ${modulePath}`)
  return defineAsyncComponent(loader as () => Promise<{ default: object }>)
})

onMounted(async () => {
  const loader = Object.values(sessionModules)[0]
  if (!loader) return
  const module = await loader() as { useSessionStore?: () => { ready: boolean; restore: () => Promise<void> } }
  const session = module.useSessionStore?.()
  if (session && !session.ready) await session.restore()
})
</script>

<template>
  <div class="erp-compat-page">
    <component :is="page" />
  </div>
</template>
