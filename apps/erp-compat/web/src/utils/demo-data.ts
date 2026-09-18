import type { DailyBalance, Operator, OperatorAccount, ReportRow } from '@/api/types'
import { previewCalculation } from './money'

export const demoOperators: Operator[] = [
  {
    id: 'op-aa', code: 'AA', name: '示例投放公司 AA', type: 'COMPANY', status: 'ACTIVE',
    contactName: 'Amit Kumar', contactValue: 'Telegram: @aa_media', remark: '印度 Facebook 投放公司',
  },
  {
    id: 'op-bb', code: 'BB', name: '示例投放公司 BB', type: 'COMPANY', status: 'ACTIVE',
    contactName: 'Ravi Singh', contactValue: 'WhatsApp: +91 98****', remark: '投放线按 USDT 独立核算',
  },
  {
    id: 'op-cc', code: 'CC', name: '示例投放公司 CC', type: 'COMPANY', status: 'INACTIVE',
    contactName: 'Mohan', contactValue: 'Telegram: @cc_ads', remark: '已停用，保留历史账目',
  },
]

export const demoAccounts: OperatorAccount[] = [
  {
    id: 'acc-aa-usdt', operatorId: 'op-aa', companyName: '示例投放公司 AA', displayName: '示例投放公司 AA · 主投放线', code: 'AA-USDT', name: '主投放线', asset: 'USDT', network: 'TRC20', walletAddress: 'TN6X...mB8p', startDate: '2026-07-01',
    defaultExchangeLossRate: '0.02', defaultExchangeLossBasis: 'TRANSFER', defaultServiceFeeRate: '0.02', defaultServiceFeeBasis: 'TRANSFER', calculationScale: 2, status: 'ACTIVE',
  },
  {
    id: 'acc-aa-usdc', operatorId: 'op-aa', companyName: '示例投放公司 AA', displayName: '示例投放公司 AA · USDC 备用线', code: 'AA-USDC', name: 'USDC 备用线', asset: 'USDC', network: 'ERC20', walletAddress: '0x53a...B280', startDate: '2026-07-15',
    defaultExchangeLossRate: '0', defaultExchangeLossBasis: 'TRANSFER', defaultServiceFeeRate: '0.015', defaultServiceFeeBasis: 'TRANSFER', calculationScale: 2, status: 'ACTIVE',
  },
  {
    id: 'acc-bb-usdt', operatorId: 'op-bb', companyName: '示例投放公司 BB', displayName: '示例投放公司 BB · 主投放线', code: 'BB-USDT', name: '主投放线', asset: 'USDT', network: 'TRC20', walletAddress: 'TP5e...Bq7N', startDate: '2026-07-01',
    defaultExchangeLossRate: '0.02', defaultExchangeLossBasis: 'TRANSFER', defaultServiceFeeRate: '0.02', defaultServiceFeeBasis: 'TRANSFER', calculationScale: 2, status: 'ACTIVE',
  },
  {
    id: 'acc-cc-usdt', operatorId: 'op-cc', companyName: '示例投放公司 CC', displayName: '示例投放公司 CC · 历史投放线', code: 'CC-USDT', name: '历史投放线', asset: 'USDT', network: 'TRC20', startDate: '2026-05-01',
    defaultExchangeLossRate: '0.02', defaultExchangeLossBasis: 'TRANSFER', defaultServiceFeeRate: '0.02', defaultServiceFeeBasis: 'TRANSFER', calculationScale: 2, status: 'INACTIVE',
  },
]

function withCalculation(record: DailyBalance): DailyBalance {
  return { ...record, ...previewCalculation(record) }
}

const aaRows = [
  withCalculation({
    id: 'aa-0701', accountId: 'acc-aa-usdt', operatorId: 'op-aa', businessDate: '2026-07-01', openingBalance: '100', openingMode: 'MANUAL', openingOverrideReason: '首期导入期初',
    transferAmount: '10000', fraudLossAmount: '0', fraudDeductionSource: null, spendAmount: '9500', exchangeLossRate: '0', exchangeLossBasis: 'TRANSFER', exchangeLossAmount: '0', exchangeLossMode: 'AUTO',
    serviceFeeRate: '0.02', serviceFeeBasis: 'SPEND', serviceFeeAmount: '190', serviceFeeMode: 'AUTO', refluxAmount: '10', refundAmount: '1', otherDeductionAmount: '0', status: 'CONFIRMED', calculationScale: 2, remark: '样本台账导入', rowVersion: 2,
  }),
  withCalculation({
    id: 'aa-0702', accountId: 'acc-aa-usdt', operatorId: 'op-aa', businessDate: '2026-07-02', openingBalance: '399', openingMode: 'AUTO', transferAmount: '500', fraudLossAmount: '0', fraudDeductionSource: null,
    spendAmount: '610', exchangeLossRate: '0.02', exchangeLossBasis: 'TRANSFER', exchangeLossAmount: '10', exchangeLossMode: 'AUTO', serviceFeeRate: '0.02', serviceFeeBasis: 'SPEND', serviceFeeAmount: '12.2', serviceFeeMode: 'AUTO',
    refluxAmount: '0', refundAmount: '0', otherDeductionAmount: '0', status: 'DRAFT', calculationScale: 2, remark: '', rowVersion: 1,
  }),
  withCalculation({
    id: 'aa-0703', accountId: 'acc-aa-usdt', operatorId: 'op-aa', businessDate: '2026-07-03', openingBalance: '266.8', openingMode: 'AUTO', transferAmount: '0', fraudLossAmount: '0', fraudDeductionSource: null,
    spendAmount: '180', exchangeLossRate: '0.02', exchangeLossBasis: 'TRANSFER', exchangeLossAmount: '0', exchangeLossMode: 'AUTO', serviceFeeRate: '0.02', serviceFeeBasis: 'SPEND', serviceFeeAmount: '3.6', serviceFeeMode: 'AUTO',
    refluxAmount: '0', refundAmount: '0', otherDeductionAmount: '0', status: 'DRAFT', calculationScale: 2, remark: '', rowVersion: 1,
  }),
]

const bbRows = [
  withCalculation({
    id: 'bb-0701', accountId: 'acc-bb-usdt', operatorId: 'op-bb', businessDate: '2026-07-01', openingBalance: '1', openingMode: 'MANUAL', openingOverrideReason: '首期导入期初',
    transferAmount: '500', fraudLossAmount: '0', fraudDeductionSource: null, spendAmount: '100', exchangeLossRate: '0.02', exchangeLossBasis: 'TRANSFER', exchangeLossAmount: '1', exchangeLossMode: 'MANUAL', exchangeLossOverrideReason: '按投放公司实际结算单',
    serviceFeeRate: '0.02', serviceFeeBasis: 'SPEND', serviceFeeAmount: '2', serviceFeeMode: 'AUTO', refluxAmount: '0', refundAmount: '0', otherDeductionAmount: '0', status: 'CONFIRMED', calculationScale: 2, remark: '样本台账导入', rowVersion: 2,
  }),
  withCalculation({
    id: 'bb-0702', accountId: 'acc-bb-usdt', operatorId: 'op-bb', businessDate: '2026-07-02', openingBalance: '398', openingMode: 'AUTO', transferAmount: '500', fraudLossAmount: '0', fraudDeductionSource: null,
    spendAmount: '720', exchangeLossRate: '0.02', exchangeLossBasis: 'TRANSFER', exchangeLossAmount: '10', exchangeLossMode: 'AUTO', serviceFeeRate: '0.02', serviceFeeBasis: 'SPEND', serviceFeeAmount: '14.4', serviceFeeMode: 'AUTO',
    refluxAmount: '0', refundAmount: '0', otherDeductionAmount: '0', status: 'DRAFT', calculationScale: 2, remark: '', rowVersion: 1,
  }),
]

export const demoBalances: DailyBalance[] = [...aaRows, ...bbRows]

export function blankBalance(account: OperatorAccount, businessDate: string, openingBalance = '0'): DailyBalance {
  return withCalculation({
    accountId: account.id,
    operatorId: account.operatorId,
    businessDate,
    openingBalance,
    openingMode: 'AUTO',
    transferAmount: '0',
    fraudLossAmount: '0',
    fraudDeductionSource: null,
    spendAmount: '0',
    exchangeLossRate: account.defaultExchangeLossRate,
    exchangeLossBasis: account.defaultExchangeLossBasis,
    exchangeLossAmount: '0',
    exchangeLossMode: 'AUTO',
    serviceFeeRate: account.defaultServiceFeeRate,
    serviceFeeBasis: account.defaultServiceFeeBasis,
    serviceFeeAmount: '0',
    serviceFeeMode: 'AUTO',
    refluxAmount: '0',
    refundAmount: '0',
    otherDeductionAmount: '0',
    status: 'DRAFT',
    sourceType: 'MANUAL',
    calculationScale: account.calculationScale,
    remark: '',
    rowVersion: 0,
  })
}

export function demoBalanceRows(account: OperatorAccount, month: string): DailyBalance[] {
  const saved = demoBalances.filter((row) => row.accountId === account.id && row.businessDate.startsWith(month))
  const count = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0).getDate()
  const rows: DailyBalance[] = []
  let previous = saved.length ? saved[0].openingBalance : '0'
  for (let day = 1; day <= count; day += 1) {
    const businessDate = `${month}-${String(day).padStart(2, '0')}`
    const existing = saved.find((row) => row.businessDate === businessDate)
    const row = existing ? { ...existing } : blankBalance(account, businessDate, previous)
    rows.push(row)
    previous = row.closingBalance || previous
  }
  return rows
}

export const demoDailyReport: ReportRow[] = [
  {
    businessDate: '2026-07-01', asset: 'USDT', openingBalance: '101', transferAmount: '10500', fraudFromTransfer: '0', effectiveTransferAmount: '10500', spendAmount: '9600', exchangeLossAmount: '1', serviceFeeAmount: '192', refluxAmount: '10', refundAmount: '1', otherDeductionAmount: '0', fraudFromBalance: '0', closingBalance: '797', recordCount: 2,
  },
  {
    businessDate: '2026-07-02', asset: 'USDT', openingBalance: '797', transferAmount: '1000', fraudFromTransfer: '0', effectiveTransferAmount: '1000', spendAmount: '1330', exchangeLossAmount: '20', serviceFeeAmount: '26.6', refluxAmount: '0', refundAmount: '0', otherDeductionAmount: '0', fraudFromBalance: '0', closingBalance: '420.4', recordCount: 2,
  },
  {
    businessDate: '2026-07-03', asset: 'USDT', openingBalance: '420.4', transferAmount: '0', fraudFromTransfer: '0', effectiveTransferAmount: '0', spendAmount: '180', exchangeLossAmount: '0', serviceFeeAmount: '3.6', refluxAmount: '0', refundAmount: '0', otherDeductionAmount: '0', fraudFromBalance: '0', closingBalance: '236.8', recordCount: 1,
  },
]

export const demoMonthlyReport: ReportRow[] = [
  {
    periodMonth: '2026-07', asset: 'USDT', openingBalance: '101', transferAmount: '11500', fraudFromTransfer: '0', effectiveTransferAmount: '11500', spendAmount: '11110', exchangeLossAmount: '21', serviceFeeAmount: '222.2', refluxAmount: '10', refundAmount: '1', otherDeductionAmount: '0', fraudFromBalance: '0', closingBalance: '236.8', recordCount: 5,
  },
]
