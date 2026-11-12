<script setup lang="ts">
import RedemptionCampaignPage from './RedemptionCampaignPage.vue'
</script>

<template>
  <RedemptionCampaignPage :key="String($route.params.taskId)" />
</template>
