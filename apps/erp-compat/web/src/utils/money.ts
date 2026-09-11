import Decimal from 'decimal.js'
import type { CalculationBasis, DailyBalance, FraudSource } from '@/api/types'

Decimal.set({ precision: 30, rounding: Decimal.ROUND_HALF_UP })

export const ZERO = '0'

export function toDecimal(value: string | number | null | undefined) {
  try {
    return new Decimal(value === '' || value === null || value === undefined ? 0 : value)
  } catch {
    return new Decimal(0)
  }
}

export function money(value: string | number | null | undefined, digits = 2) {
  return toDecimal(value).toFixed(digits, Decimal.ROUND_HALF_UP).replace(/(\.\d*?[1-9])0+$|\.0+$/, '$1')
}

export function formatMoney(value: string | number | null | undefined, digits = 2) {
  return Number(money(value, digits)).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function percent(value: string | number | null | undefined) {
  return toDecimal(value).mul(100).toFixed(2).replace(/\.00$/, '')
}

export function fromPercent(value: string | number | null | undefined) {
  return toDecimal(value).div(100).toString()
}

function baseOf(record: Partial<DailyBalance>, basis: CalculationBasis, effectiveTransfer: Decimal) {
  switch (basis) {
    case 'TRANSFER': return toDecimal(record.transferAmount)
    case 'EFFECTIVE_TRANSFER': return effectiveTransfer
    case 'SPEND': return toDecimal(record.spendAmount)
    case 'MANUAL': return new Decimal(0)
  }
}

export function previewCalculation(record: Partial<DailyBalance>) {
  const scale = record.calculationScale ?? 2
  const fraudLoss = toDecimal(record.fraudLossAmount)
  const fraudFromTransfer = (record.fraudDeductionSource as FraudSource) === 'TRANSFER' ? fraudLoss : new Decimal(0)
  const fraudFromBalance = (record.fraudDeductionSource as FraudSource) === 'BALANCE' ? fraudLoss : new Decimal(0)
  const effectiveTransfer = toDecimal(record.transferAmount).minus(fraudFromTransfer)
  const exchangeLossAuto = baseOf(record, record.exchangeLossBasis ?? 'TRANSFER', effectiveTransfer)
    .mul(toDecimal(record.exchangeLossRate)).toDecimalPlaces(scale)
  const serviceFeeAuto = baseOf(record, record.serviceFeeBasis ?? 'TRANSFER', effectiveTransfer)
    .mul(toDecimal(record.serviceFeeRate)).toDecimalPlaces(scale)
  const exchangeLoss = record.exchangeLossMode === 'MANUAL' ? toDecimal(record.exchangeLossAmount) : exchangeLossAuto
  const serviceFee = record.serviceFeeMode === 'MANUAL' ? toDecimal(record.serviceFeeAmount) : serviceFeeAuto
  const closingBalance = toDecimal(record.openingBalance)
    .plus(effectiveTransfer)
    .minus(toDecimal(record.spendAmount))
    .minus(exchangeLoss)
    .minus(serviceFee)
    .minus(toDecimal(record.refluxAmount))
    .minus(toDecimal(record.refundAmount))
    .minus(toDecimal(record.otherDeductionAmount))
    .minus(fraudFromBalance)

  return {
    effectiveTransferAmount: effectiveTransfer.toFixed(scale),
    exchangeLossAutoAmount: exchangeLossAuto.toFixed(scale),
    exchangeLossAmount: exchangeLoss.toFixed(scale),
    serviceFeeAutoAmount: serviceFeeAuto.toFixed(scale),
    serviceFeeAmount: serviceFee.toFixed(scale),
    fraudFromTransfer: fraudFromTransfer.toFixed(scale),
    fraudFromBalance: fraudFromBalance.toFixed(scale),
    closingBalance: closingBalance.toFixed(scale),
  }
}
