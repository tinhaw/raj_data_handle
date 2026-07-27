import { api } from './client'
import type {
  PaymentChannelBinding,
  TemplateDetection,
} from '../types'

export async function detectPaymentTemplate(file: File): Promise<TemplateDetection> {
  const form = new FormData()
  form.set('upload', file)
  const response = await api.post<TemplateDetection>(
    '/payment-template-versions/detect',
    form,
  )
  return response.data
}

export async function fetchPaymentChannelBindings(params: {
  sourceId?: string
  businessType?: 'payin' | 'payout'
}): Promise<PaymentChannelBinding[]> {
  const response = await api.get<PaymentChannelBinding[]>(
    '/payment-channel-bindings',
    {
      params: {
        source_id: params.sourceId,
        business_type: params.businessType,
      },
    },
  )
  return response.data
}
