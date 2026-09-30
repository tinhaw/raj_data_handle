/** 演示数据只能由开发者显式开启，生产/API 不可用时绝不伪装成正式账目。 */
export const demoEnabled = import.meta.env.VITE_ENABLE_DEMO === 'true'
