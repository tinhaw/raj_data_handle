<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { ApiError } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const router = useRouter()
const route = useRoute()
const session = useSessionStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function submit() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await session.login(form.username.trim(), form.password)
    if (session.demoMode) ElMessage.warning('无法连接后端，已进入演示数据模式')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    await router.replace(redirect)
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-intro">
      <div class="intro-scanline" aria-hidden="true"></div>
      <div class="login-brand"><span class="login-mark">R</span><strong>Raj ERP</strong></div>
      <div class="intro-content">
        <span class="eyebrow">ENTERPRISE OPERATIONS SYSTEM</span>
        <h1>统一、清晰地驱动<br />企业经营协作</h1>
        <p>从基础资料、资金结算到数据导入、报表与审计，让每一项日常工作都可追溯、可协同。</p>
        <div class="intro-points">
          <div><span>✓</span> 统一日结与公式计算</div>
          <div><span>✓</span> 多角色权限与数据范围</div>
          <div><span>✓</span> 导入、审计与期间治理</div>
        </div>
      </div>
      <p class="intro-foot">Raj ERP · 内部系统，请勿共享登录凭据</p>
    </section>

    <section class="login-panel">
      <div class="login-card">
        <div class="login-card-heading">
          <h2>欢迎回来</h2>
          <p>请使用公司账号进入 Raj ERP 工作台</p>
        </div>
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input v-model="form.username" size="large" autocomplete="username" placeholder="请输入用户名" :prefix-icon="User" @keyup.enter="submit" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" size="large" type="password" show-password autocomplete="current-password" placeholder="请输入密码" :prefix-icon="Lock" @keyup.enter="submit" />
          </el-form-item>
          <div class="login-row">
            <el-checkbox>记住本次登录</el-checkbox>
            <a href="javascript:void(0)">忘记密码？</a>
          </div>
          <el-button class="login-submit" type="primary" size="large" :loading="loading" native-type="submit">登录系统</el-button>
        </el-form>
        <el-alert class="demo-login-note" type="info" :closable="false" show-icon>
          初始管理员由部署环境中的 <b>ERP_BOOTSTRAP_ADMIN_*</b> 配置；演示模式仅在显式设置 <b>VITE_ENABLE_DEMO=true</b> 时可用。
        </el-alert>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page { display: grid; grid-template-columns: minmax(470px, 46%) 1fr; min-width: 100vw; min-height: 100vh; background: #fff; }
.login-intro { position: relative; display: flex; flex-direction: column; min-height: 100vh; padding: 42px 8.5%; overflow: hidden; isolation: isolate; color: #fff; background: radial-gradient(circle at 15% 86%, rgba(62, 129, 255, .42), transparent 29%), radial-gradient(circle at 90% 10%, rgba(88, 214, 204, .2), transparent 23%), linear-gradient(145deg, #102a56, #155eef 68%, #1545bb); }
.login-intro::before { position: absolute; inset: -34% -44% -48%; content: ''; pointer-events: none; background-image: linear-gradient(rgba(217, 233, 255, .21) 1px, transparent 1px), linear-gradient(90deg, rgba(217, 233, 255, .21) 1px, transparent 1px); background-size: 34px 34px; opacity: .46; transform: perspective(620px) rotateX(60deg) translate3d(0, 6%, 0); transform-origin: center bottom; mask-image: linear-gradient(to bottom, transparent 4%, rgba(0, 0, 0, .86) 45%, transparent 88%); -webkit-mask-image: linear-gradient(to bottom, transparent 4%, rgba(0, 0, 0, .86) 45%, transparent 88%); animation: login-grid-drift 18s linear infinite; }
.login-intro::after { position: absolute; right: -115px; bottom: -120px; width: 430px; height: 430px; content: ''; border: 1px solid rgba(255, 255, 255, .18); border-radius: 50%; box-shadow: 0 0 0 44px rgba(255, 255, 255, .05), 0 0 0 88px rgba(255, 255, 255, .04); animation: login-radar-pulse 7s ease-in-out infinite; }
.intro-scanline { position: absolute; z-index: 0; top: -12%; bottom: -12%; left: -56%; width: 34%; pointer-events: none; background: linear-gradient(90deg, transparent, rgba(204, 244, 255, .03) 22%, rgba(204, 244, 255, .24) 50%, rgba(204, 244, 255, .03) 78%, transparent); transform: skewX(-18deg); filter: blur(1px); animation: login-scan 10s cubic-bezier(.42, 0, .32, 1) infinite; }
.login-brand { position: relative; z-index: 1; display: flex; align-items: center; gap: 10px; font-size: 18px; animation: login-reveal .6s .05s both; }
.login-mark { position: relative; display: grid; place-items: center; width: 34px; height: 34px; overflow: hidden; font-weight: 800; background: rgba(255, 255, 255, .18); border: 1px solid rgba(255, 255, 255, .25); border-radius: 9px; box-shadow: 0 7px 20px rgba(4, 22, 71, .22); animation: login-mark-float 4.8s ease-in-out infinite; }
.login-mark::after { position: absolute; inset: -40% auto -40% -50%; width: 38%; content: ''; opacity: 0; background: rgba(255, 255, 255, .48); transform: skewX(-22deg); animation: login-mark-sheen 4.8s ease-in-out infinite; }
.intro-content { position: relative; z-index: 1; margin: auto 0; }
.intro-content > * { opacity: 0; animation: login-reveal .68s cubic-bezier(.22, 1, .36, 1) both; }
.eyebrow { color: #b2ccff; font-size: 12px; font-weight: 700; letter-spacing: .12em; animation-delay: .14s; }
.intro-content h1 { margin: 17px 0; font-size: clamp(35px, 3.5vw, 52px); line-height: 1.18; letter-spacing: -.04em; }
.intro-content h1 { animation-delay: .22s; }
.intro-content p { max-width: 410px; color: #d1e0ff; font-size: 16px; line-height: 1.75; animation-delay: .3s; }
.intro-points { display: grid; gap: 13px; margin-top: 36px; color: #e7efff; font-size: 14px; animation-delay: .38s; }
.intro-points span { display: inline-grid; place-items: center; width: 19px; height: 19px; margin-right: 8px; color: #155eef; font-size: 12px; font-weight: 800; background: #fff; border-radius: 50%; }
.intro-foot { position: relative; z-index: 1; margin: 0; color: #b2ccff; font-size: 12px; animation: login-reveal .6s .5s both; }
.login-panel { display: grid; place-items: center; padding: 48px; background: #fff; }
.login-card { width: min(390px, 100%); animation: login-card-enter .64s .12s cubic-bezier(.22, 1, .36, 1) both; }
.login-card-heading { margin-bottom: 32px; }
.login-card-heading h2 { margin: 0 0 8px; color: #101828; font-size: 28px; letter-spacing: -.03em; }
.login-card-heading p { margin: 0; color: #667085; font-size: 14px; }
.login-row { display: flex; align-items: center; justify-content: space-between; margin: -2px 0 24px; font-size: 13px; }
.login-row a { color: #155eef; text-decoration: none; }
.login-submit { width: 100%; }
.demo-login-note { margin-top: 20px; font-size: 12px; line-height: 1.55; }
@keyframes login-grid-drift { from { transform: perspective(620px) rotateX(60deg) translate3d(0, 6%, 0); } to { transform: perspective(620px) rotateX(60deg) translate3d(-34px, -28px, 0); } }
@keyframes login-radar-pulse { 0%, 100% { opacity: .72; transform: scale(1); } 50% { opacity: 1; transform: scale(1.07); } }
@keyframes login-scan { 0%, 18% { transform: translateX(0) skewX(-18deg); opacity: 0; } 25% { opacity: .9; } 70% { transform: translateX(460%) skewX(-18deg); opacity: .55; } 82%, 100% { transform: translateX(510%) skewX(-18deg); opacity: 0; } }
@keyframes login-mark-float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-3px); } }
@keyframes login-mark-sheen { 0%, 62% { transform: translateX(0) skewX(-22deg); opacity: 0; } 68% { opacity: 1; } 84%, 100% { transform: translateX(320%) skewX(-22deg); opacity: 0; } }
@keyframes login-reveal { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
@keyframes login-card-enter { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }
@media (prefers-reduced-motion: reduce) { .login-intro::before, .login-intro::after, .intro-scanline, .login-brand, .login-mark, .login-mark::after, .intro-content > *, .intro-foot, .login-card { animation: none !important; } .intro-content > * { opacity: 1; } }
@media (max-width: 900px) { .login-page { grid-template-columns: 1fr; } .login-intro { display: none; } }
</style>
