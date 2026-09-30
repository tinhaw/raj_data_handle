package com.rajads.erp.reporting;

import com.rajads.erp.balance.DailyBalance;
import com.rajads.erp.balance.DailyBalanceRepository;
import com.rajads.erp.identity.OperatorAccessService;
import com.rajads.erp.operator.OperatorAccount;
import com.rajads.erp.operator.OperatorAccountRepository;
import com.rajads.erp.shared.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.*;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ReportService {
    private final DailyBalanceRepository balanceRepository;
    private final OperatorAccountRepository accountRepository;
    private final OperatorAccessService accessService;

    @Transactional(readOnly = true)
    public ReportDtos.ReportResponse daily(LocalDate from, LocalDate to, List<Long> operatorIds, Long accountId,
                                           String asset, boolean includeDraft, boolean nominalU) {
        return daily(from, to, operatorIds, accountId, null, asset, includeDraft, nominalU);
    }

    /**
     * {@code accountIds} is the multi-select counterpart to the legacy
     * {@code accountId} parameter.  Both are accepted during the API
     * transition and are combined into one explicit line selection.
     */
    @Transactional(readOnly = true)
    public ReportDtos.ReportResponse daily(LocalDate from, LocalDate to, List<Long> operatorIds, Long accountId,
                                           List<Long> accountIds, String asset, boolean includeDraft, boolean nominalU) {
        if (from == null || to == null || to.isBefore(from)) throw ApiException.badRequest("INVALID_DATE_RANGE", "请选择有效的日期范围");
        List<OperatorAccount> accounts = selectedAccounts(operatorIds, accountId, accountIds, asset);
        Map<Long, List<DailyBalance>> recordsByAccount = recordsFor(accounts, from.minusDays(1), to, includeDraft);
        List<ReportDtos.ReportRow> rows = new ArrayList<>();
        LocalDate date = from;
        while (!date.isAfter(to)) {
            if (nominalU) {
                rows.add(aggregateDay(date, null, accounts, recordsByAccount));
            } else {
                for (String unit : assets(accounts)) rows.add(aggregateDay(date, unit, accounts, recordsByAccount));
            }
            date = date.plusDays(1);
        }
        return new ReportDtos.ReportResponse("DAILY", nominalU, rows);
    }

    @Transactional(readOnly = true)
    public ReportDtos.ReportResponse monthly(YearMonth from, YearMonth to, List<Long> operatorIds, Long accountId,
                                             String asset, boolean includeDraft, boolean nominalU) {
        return monthly(from, to, operatorIds, accountId, null, asset, includeDraft, nominalU);
    }

    /** See {@link #daily(LocalDate, LocalDate, List, Long, List, String, boolean, boolean)}. */
    @Transactional(readOnly = true)
    public ReportDtos.ReportResponse monthly(YearMonth from, YearMonth to, List<Long> operatorIds, Long accountId,
                                             List<Long> accountIds, String asset, boolean includeDraft, boolean nominalU) {
        if (from == null || to == null || to.isBefore(from)) throw ApiException.badRequest("INVALID_MONTH_RANGE", "请选择有效的月份范围");
        List<OperatorAccount> accounts = selectedAccounts(operatorIds, accountId, accountIds, asset);
        LocalDate first = from.atDay(1);
        LocalDate last = to.atEndOfMonth();
        Map<Long, List<DailyBalance>> recordsByAccount = recordsFor(accounts, first.minusDays(1), last, includeDraft);
        List<ReportDtos.ReportRow> rows = new ArrayList<>();
        for (YearMonth month = from; !month.isAfter(to); month = month.plusMonths(1)) {
            if (nominalU) rows.add(aggregateMonth(month, null, accounts, recordsByAccount));
            else for (String unit : assets(accounts)) rows.add(aggregateMonth(month, unit, accounts, recordsByAccount));
        }
        return new ReportDtos.ReportResponse("MONTHLY", nominalU, rows);
    }

    private ReportDtos.ReportRow aggregateDay(LocalDate date, String asset, List<OperatorAccount> accounts,
                                               Map<Long, List<DailyBalance>> recordsByAccount) {
        Totals totals = new Totals();
        for (OperatorAccount account : filterByAsset(accounts, asset)) {
            if (account.getStartDate() != null && account.getStartDate().isAfter(date)) continue;
            DailyBalance day = onDate(recordsByAccount.get(account.getId()), date);
            BigDecimal opening = day == null ? asOf(recordsByAccount.get(account.getId()), date.minusDays(1)) : day.getOpeningBalance();
            BigDecimal closing = day == null ? opening : day.getClosingBalance();
            totals.opening = totals.opening.add(opening); totals.closing = totals.closing.add(closing);
            if (day != null) totals.addFlow(day);
        }
        return totals.toRow(date.toString(), asset == null ? "NOMINAL_U" : asset);
    }

    private ReportDtos.ReportRow aggregateMonth(YearMonth month, String asset, List<OperatorAccount> accounts,
                                                 Map<Long, List<DailyBalance>> recordsByAccount) {
        Totals totals = new Totals();
        for (OperatorAccount account : filterByAsset(accounts, asset)) {
            if (account.getStartDate() != null && account.getStartDate().isAfter(month.atEndOfMonth())) continue;
            List<DailyBalance> records = recordsByAccount.getOrDefault(account.getId(), List.of());
            BigDecimal opening = openingForMonth(records, month);
            BigDecimal closing = asOf(records, month.atEndOfMonth());
            totals.opening = totals.opening.add(opening); totals.closing = totals.closing.add(closing);
            for (DailyBalance record : records) {
                if (!record.getBusinessDate().isBefore(month.atDay(1)) && !record.getBusinessDate().isAfter(month.atEndOfMonth())) {
                    totals.addFlow(record);
                }
            }
        }
        BigDecimal expected = totals.opening.add(totals.effectiveTransfer).subtract(totals.spend)
                .subtract(totals.exchangeLoss).subtract(totals.serviceFee).subtract(totals.reflux)
                .subtract(totals.refund).subtract(totals.other).subtract(totals.fraudBalance);
        if (expected.compareTo(totals.closing) != 0) {
            totals.warnings.add("月期末与月期初加发生额不一致；可能存在期初人工锚点或范围外历史调整");
        }
        return totals.toRow(month.toString(), asset == null ? "NOMINAL_U" : asset);
    }

    private List<OperatorAccount> selectedAccounts(List<Long> operatorIds, Long accountId, List<Long> accountIds, String asset) {
        if (operatorIds != null && !operatorIds.isEmpty()) accessService.requireAccess(operatorIds);
        List<OperatorAccount> accounts;
        LinkedHashSet<Long> selectedAccountIds = selectedAccountIds(accountId, accountIds);
        if (!selectedAccountIds.isEmpty()) {
            Map<Long, OperatorAccount> byId = accountRepository.findAllById(selectedAccountIds).stream()
                    .collect(Collectors.toMap(OperatorAccount::getId, account -> account));
            if (byId.size() != selectedAccountIds.size()) throw ApiException.notFound("投放线");

            Set<Long> selectedOperatorIds = operatorIds == null ? Set.of() : new HashSet<>(operatorIds);
            accounts = new ArrayList<>(selectedAccountIds.size());
            for (Long selectedAccountId : selectedAccountIds) {
                OperatorAccount account = byId.get(selectedAccountId);
                accessService.requireAccess(account.getOperatorId());
                if (!selectedOperatorIds.isEmpty() && !selectedOperatorIds.contains(account.getOperatorId())) {
                    throw ApiException.badRequest("ACCOUNT_OUTSIDE_OPERATOR_SELECTION", "所选投放线不属于已选择的投放公司");
                }
                accounts.add(account);
            }
        } else if (operatorIds != null && !operatorIds.isEmpty()) {
            accounts = accountRepository.findByOperatorIdIn(operatorIds);
        } else if (accessService.hasAllOperators()) {
            accounts = accountRepository.findAll();
        } else {
            accounts = accountRepository.findByOperatorIdIn(accessService.accessibleOperatorIds());
        }
        if (asset != null && !asset.isBlank()) {
            String normalized = asset.trim().toUpperCase(Locale.ROOT);
            accounts = accounts.stream().filter(account -> normalized.equals(account.getAsset())).toList();
        }
        return accounts;
    }

    private LinkedHashSet<Long> selectedAccountIds(Long accountId, List<Long> accountIds) {
        LinkedHashSet<Long> ids = new LinkedHashSet<>();
        if (accountId != null) ids.add(accountId);
        if (accountIds != null) accountIds.stream().filter(Objects::nonNull).forEach(ids::add);
        return ids;
    }

    private Map<Long, List<DailyBalance>> recordsFor(List<OperatorAccount> accounts, LocalDate from, LocalDate to, boolean includeDraft) {
        if (accounts.isEmpty()) return Map.of();
        return balanceRepository.findByOperatorAccountIdInAndBusinessDateLessThanEqualOrderByBusinessDateAsc(
                        accounts.stream().map(OperatorAccount::getId).toList(), to).stream()
                .filter(record -> includeDraft || "CONFIRMED".equals(record.getStatus()))
                .collect(Collectors.groupingBy(DailyBalance::getOperatorAccountId));
    }
    private List<OperatorAccount> filterByAsset(List<OperatorAccount> accounts, String asset) {
        return asset == null ? accounts : accounts.stream().filter(a -> asset.equals(a.getAsset())).toList();
    }
    private List<String> assets(List<OperatorAccount> accounts) {
        return accounts.stream().map(OperatorAccount::getAsset).distinct().sorted().toList();
    }
    private DailyBalance onDate(List<DailyBalance> records, LocalDate date) {
        if (records == null) return null;
        return records.stream().filter(record -> record.getBusinessDate().equals(date)).findFirst().orElse(null);
    }
    private BigDecimal asOf(List<DailyBalance> records, LocalDate date) {
        if (records == null) return BigDecimal.ZERO;
        return records.stream().filter(record -> !record.getBusinessDate().isAfter(date))
                .max(Comparator.comparing(DailyBalance::getBusinessDate))
                .map(DailyBalance::getClosingBalance).orElse(BigDecimal.ZERO);
    }

    /**
     * A month starts from the latest confirmed balance before the month.  For a
     * newly-created account there is no such balance, so its first recorded day
     * in the month establishes the opening balance instead of defaulting to 0.
     */
    private BigDecimal openingForMonth(List<DailyBalance> records, YearMonth month) {
        if (records == null || records.isEmpty()) return BigDecimal.ZERO;
        LocalDate firstDay = month.atDay(1);
        LocalDate lastDay = month.atEndOfMonth();
        Optional<DailyBalance> priorRecord = records.stream()
                .filter(record -> record.getBusinessDate().isBefore(firstDay))
                .max(Comparator.comparing(DailyBalance::getBusinessDate));
        if (priorRecord.isPresent()) return priorRecord.get().getClosingBalance();

        return records.stream()
                .filter(record -> !record.getBusinessDate().isBefore(firstDay)
                        && !record.getBusinessDate().isAfter(lastDay))
                .min(Comparator.comparing(DailyBalance::getBusinessDate))
                .map(DailyBalance::getOpeningBalance)
                .orElse(BigDecimal.ZERO);
    }

    private static final class Totals {
        BigDecimal opening = BigDecimal.ZERO, transfer = BigDecimal.ZERO, fraudTransfer = BigDecimal.ZERO,
                effectiveTransfer = BigDecimal.ZERO, spend = BigDecimal.ZERO, exchangeLoss = BigDecimal.ZERO,
                serviceFee = BigDecimal.ZERO, reflux = BigDecimal.ZERO, refund = BigDecimal.ZERO, other = BigDecimal.ZERO,
                fraudBalance = BigDecimal.ZERO, closing = BigDecimal.ZERO;
        long recordCount;
        List<String> warnings = new ArrayList<>();
        void addFlow(DailyBalance d) {
            transfer = transfer.add(d.getTransferAmount()); effectiveTransfer = effectiveTransfer.add(d.getEffectiveTransferAmount());
            spend = spend.add(d.getSpendAmount()); exchangeLoss = exchangeLoss.add(d.getExchangeLossAmount()); serviceFee = serviceFee.add(d.getServiceFeeAmount());
            reflux = reflux.add(d.getRefluxAmount()); refund = refund.add(d.getRefundAmount()); other = other.add(d.getOtherDeductionAmount()); recordCount++;
            if ("TRANSFER".equals(d.getFraudDeductionSource())) fraudTransfer = fraudTransfer.add(d.getFraudLossAmount());
            if ("BALANCE".equals(d.getFraudDeductionSource())) fraudBalance = fraudBalance.add(d.getFraudLossAmount());
        }
        ReportDtos.ReportRow toRow(String period, String asset) {
            return new ReportDtos.ReportRow(period, asset, opening, transfer, fraudTransfer, effectiveTransfer, spend,
                    exchangeLoss, serviceFee, reflux, refund, other, fraudBalance, closing, recordCount, warnings);
        }
    }
}
