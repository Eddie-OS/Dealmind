import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import './styles/global.scss'

const app = createApp(App)
app.config.errorHandler = (err, _instance, info) => {
  console.error('[DealMind] Vue errorHandler:', err, info)
}
window.addEventListener('unhandledrejection', (e) => {
  console.error('[DealMind] unhandledrejection:', e.reason)
})
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
