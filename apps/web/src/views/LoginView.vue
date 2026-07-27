<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchCaptcha, login } from '../api/auth'
import { apiErrorMessage } from '../api/client'
import { setCurrentUser } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const captchaLoading = ref(false)
const captchaId = ref('')
const captchaImage = ref('')
const form = reactive({
  username: window.localStorage.getItem('raj-remembered-username') || '',
  password: '',
  captchaCode: '',
  rememberUsername: true,
})

const redirectTarget = computed(() =>
  typeof route.query.redirect === 'string' ? route.query.redirect : '/batches',
)

async function loadCaptcha(): Promise<void> {
  captchaLoading.value = true
  try {
    const result = await fetchCaptcha()
    captchaId.value = result.captchaId
    captchaImage.value = result.image
    form.captchaCode = ''
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '验证码加载失败。'))
  } finally {
    captchaLoading.value = false
  }
}

async function submit(): Promise<void> {
  if (!form.username.trim() || !form.password || !form.captchaCode.trim()) {
    ElMessage.warning('请完整填写用户名、密码和验证码。')
    return
  }
  loading.value = true
  try {
    const user = await login({
      username: form.username.trim(),
      password: form.password,
      captchaId: captchaId.value,
      captchaCode: form.captchaCode.trim(),
    })
    if (form.rememberUsername) {
      window.localStorage.setItem('raj-remembered-username', user.username)
    } else {
      window.localStorage.removeItem('raj-remembered-username')
    }
    form.password = ''
    setCurrentUser(user)
    await router.replace(redirectTarget.value)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '登录失败。'))
    form.password = ''
    await loadCaptcha()
  } finally {
    loading.value = false
  }
}

onMounted(loadCaptcha)
</script>

<template>
  <div class="login-page">
    <div class="login-glow login-glow--one" />
    <div class="login-glow login-glow--two" />
    <section class="login-card">
      <div class="login-intro">
        <span class="brand-badge">RAJ DATA</span>
        <h1>让每一笔支付<br />都有迹可循</h1>
        <p>
          连接 RajWin 与 RajLuck，只读拉取远端订单，识别支付平台存在但管理后台遗漏或状态异常的记录。
        </p>
        <div class="security-note">
          <strong>安全边界</strong>
          <span>本系统不审核、不补单、不修改远端订单。</span>
        </div>
      </div>

      <el-form class="login-form" label-position="top" @submit.prevent="submit">
        <header>
          <span>Secure workspace</span>
          <h2>登录分析中心</h2>
          <p>使用本系统独立账号登录</p>
        </header>

        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            show-password
            placeholder="请输入密码"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-form-item label="验证码">
          <div class="captcha-row">
            <el-input
              v-model="form.captchaCode"
              maxlength="6"
              placeholder="计算结果"
              @keyup.enter="submit"
            />
            <button type="button" class="captcha-image" @click="loadCaptcha">
              <img v-if="captchaImage" :src="captchaImage" alt="算术验证码" />
              <el-icon v-else :class="{ 'is-loading': captchaLoading }"><Refresh /></el-icon>
            </button>
          </div>
        </el-form-item>
        <el-checkbox v-model="form.rememberUsername">记住用户名</el-checkbox>
        <p class="credential-hint">不会在浏览器保存密码。</p>

        <el-button class="login-submit" type="primary" :loading="loading" @click="submit">
          进入系统
        </el-button>
      </el-form>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  position: relative;
  overflow: hidden;
  display: grid;
  place-items: center;
  padding: 32px;
  background: #071827;
}

.login-page::before {
  content: '';
  position: absolute;
  inset: 0;
  opacity: 0.08;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.35) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.35) 1px, transparent 1px);
  background-size: 48px 48px;
}

.login-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(12px);
}

.login-glow--one {
  width: 460px;
  height: 460px;
  top: -180px;
  left: -120px;
  background: rgba(42, 157, 143, 0.2);
}

.login-glow--two {
  width: 360px;
  height: 360px;
  right: -100px;
  bottom: -150px;
  background: rgba(233, 196, 106, 0.16);
}

.login-card {
  width: min(980px, 100%);
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 1.12fr 0.88fr;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 28px;
  background: rgba(11, 31, 51, 0.76);
  box-shadow: 0 30px 90px rgba(0, 0, 0, 0.34);
  backdrop-filter: blur(18px);
}

.login-intro {
  min-height: 620px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 64px;
  color: #f7fbff;
  background:
    radial-gradient(circle at 20% 20%, rgba(42, 157, 143, 0.24), transparent 34%),
    linear-gradient(145deg, rgba(16, 42, 67, 0.4), rgba(11, 31, 51, 0.72));
}

.brand-badge {
  align-self: flex-start;
  padding: 8px 11px;
  border-radius: 8px;
  color: #102a43;
  background: #e9c46a;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.12em;
}

.login-intro h1 {
  margin: 30px 0 20px;
  font-size: clamp(42px, 5vw, 64px);
  line-height: 1.08;
  letter-spacing: -0.04em;
}

.login-intro > p {
  max-width: 560px;
  margin: 0;
  color: rgba(255, 255, 255, 0.66);
  font-size: 16px;
  line-height: 1.85;
}

.security-note {
  width: fit-content;
  display: grid;
  gap: 5px;
  margin-top: 54px;
  padding: 16px 18px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.05);
}

.security-note span {
  color: rgba(255, 255, 255, 0.58);
  font-size: 13px;
}

.login-form {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 52px 42px;
  background: #fbfdff;
}

.login-form header {
  margin-bottom: 28px;
}

.login-form header span {
  color: #2a9d8f;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.login-form h2 {
  margin: 8px 0 6px;
  color: #102a43;
  font-size: 29px;
}

.login-form header p,
.credential-hint {
  margin: 0;
  color: #829ab1;
  font-size: 13px;
}

.captcha-row {
  width: 100%;
  display: grid;
  grid-template-columns: 1fr 150px;
  gap: 10px;
}

.captcha-image {
  height: 40px;
  display: grid;
  place-items: center;
  overflow: hidden;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
  background: #f0f4f8;
  cursor: pointer;
}

.captcha-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.credential-hint {
  margin-top: 4px;
}

.login-submit {
  width: 100%;
  height: 44px;
  margin-top: 26px;
}

@media (max-width: 800px) {
  .login-card {
    grid-template-columns: 1fr;
  }

  .login-intro {
    min-height: auto;
    padding: 36px;
  }

  .login-intro h1 {
    font-size: 38px;
  }

  .security-note {
    margin-top: 28px;
  }

  .login-form {
    padding: 36px;
  }
}
</style>
