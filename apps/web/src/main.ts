import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import './style.css'
import './erp-preview.css'

createApp(App).use(createPinia()).use(ElementPlus).use(router).mount('#app')
