/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_ERP_COMPAT_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
