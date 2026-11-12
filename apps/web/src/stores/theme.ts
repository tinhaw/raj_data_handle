import { computed, readonly, ref } from 'vue'

export type Theme = 'light' | 'dark'
const storageKey = 'raj-ui-theme'
const currentTheme = ref<Theme>('light')

function applyTheme(theme: Theme): void {
  currentTheme.value = theme
  document.documentElement.classList.toggle('dark', theme === 'dark')
  document.documentElement.dataset.theme = theme
}

export function initializeTheme(): void {
  // Keep the current light appearance unless the user explicitly chose dark.
  let saved: string | null = null
  try {
    saved = window.localStorage.getItem(storageKey)
  } catch {
    // Theme switching still works when browser storage is unavailable.
  }
  applyTheme(saved === 'dark' ? 'dark' : 'light')
  window.addEventListener('storage', (event) => {
    if (event.key === storageKey || event.key === null) {
      applyTheme(event.newValue === 'dark' ? 'dark' : 'light')
    }
  })
}

export function setTheme(theme: Theme): void {
  applyTheme(theme)
  try {
    window.localStorage.setItem(storageKey, theme)
  } catch {
    // Do not interrupt the UI if the preference cannot be persisted.
  }
}

export const theme = readonly(currentTheme)
export const isDark = computed({
  get: () => currentTheme.value === 'dark',
  set: (value: boolean) => setTheme(value ? 'dark' : 'light'),
})
