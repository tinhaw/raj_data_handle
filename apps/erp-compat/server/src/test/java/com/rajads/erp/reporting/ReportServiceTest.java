package com.rajads.erp.reporting;

import com.rajads.erp.balance.DailyBalance;
import com.rajads.erp.balance.DailyBalanceRepository;
import com.rajads.erp.identity.OperatorAccessService;
import com.rajads.erp.operator.OperatorAccount;
import com.rajads.erp.operator.OperatorAccountRepository;
import com.rajads.erp.shared.ApiException;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ReportServiceTest {
    private final DailyBalanceRepository balanceRepository = mock(DailyBalanceRepository.class);
    private final OperatorAccountRepository accountRepository = mock(OperatorAccountRepository.class);
    private final OperatorAccessService accessService = mock(OperatorAccessService.class);
    private final ReportService reportService = new ReportService(balanceRepository, accountRepository, accessService);

    @Test
    void monthlyNominalReportUsesFirstRecordedDayOpeningWhenThereIsNoPriorBalance() {
        OperatorAccount aa = account(1L, 11L, "USDT");
        OperatorAccount bb = account(2L, 12L, "USDT");
        when(accessService.hasAllOperators()).thenReturn(true);
        when(accountRepository.findAll()).thenReturn(List.of(aa, bb));
        when(balanceRepository.findByOperatorAccountIdInAndBusinessDateLessThanEqualOrderByBusinessDateAsc(
                anyList(), eq(LocalDate.of(2026, 7, 31))))
                .thenReturn(List.of(
                        balance(1L, "2026-07-01", "100", "399"),
                        balance(2L, "2026-07-01", "1", "398")
                ));

        ReportDtos.ReportRow row = reportService.monthly(YearMonth.of(2026, 7), YearMonth.of(2026, 7),
                null, null, null, true, true).rows().getFirst();

        assertThat(row.openingBalance()).isEqualByComparingTo("101");
        assertThat(row.closingBalance()).isEqualByComparingTo("797");
    }

    @Test
    void monthlyReportUsesTheLatestBalanceBeforeTheMonthWhenItExists() {
        OperatorAccount account = account(1L, 11L, "USDT");
        when(accessService.hasAllOperators()).thenReturn(true);
        when(accountRepository.findAll()).thenReturn(List.of(account));
        when(balanceRepository.findByOperatorAccountIdInAndBusinessDateLessThanEqualOrderByBusinessDateAsc(
                anyList(), eq(LocalDate.of(2026, 7, 31))))
                .thenReturn(List.of(
                        balance(1L, "2026-06-30", "80", "90"),
                        balance(1L, "2026-07-05", "100", "120")
                ));

        ReportDtos.ReportRow row = reportService.monthly(YearMonth.of(2026, 7), YearMonth.of(2026, 7),
                null, null, null, true, true).rows().getFirst();

        assertThat(row.openingBalance()).isEqualByComparingTo("90");
        assertThat(row.closingBalance()).isEqualByComparingTo("120");
    }

    @Test
    void monthlyReportTreatsAccountsWithoutDailyBalancesAsZero() {
        OperatorAccount recordedAccount = account(1L, 11L, "USDT");
        OperatorAccount emptyAccount = account(2L, 12L, "USDT");
        when(accessService.hasAllOperators()).thenReturn(true);
        when(accountRepository.findAll()).thenReturn(List.of(recordedAccount, emptyAccount));
        when(balanceRepository.findByOperatorAccountIdInAndBusinessDateLessThanEqualOrderByBusinessDateAsc(
                anyList(), eq(LocalDate.of(2026, 7, 31))))
                .thenReturn(List.of(balance(1L, "2026-07-01", "100", "399")));

        ReportDtos.ReportRow row = reportService.monthly(YearMonth.of(2026, 7), YearMonth.of(2026, 7),
                null, null, null, true, true).rows().getFirst();

        assertThat(row.openingBalance()).isEqualByComparingTo("100");
        assertThat(row.closingBalance()).isEqualByComparingTo("399");
        assertThat(row.recordCount()).isEqualTo(1);
    }

    @Test
    void dailyReportSupportsMultipleSelectedLinesWithinTheSelectedCompany() {
        OperatorAccount first = account(1L, 11L, "USDT");
        OperatorAccount second = account(2L, 11L, "USDT");
        when(accountRepository.findAllById(any())).thenReturn(List.of(second, first));
        when(balanceRepository.findByOperatorAccountIdInAndBusinessDateLessThanEqualOrderByBusinessDateAsc(
                anyList(), eq(LocalDate.of(2026, 7, 1))))
                .thenReturn(List.of(
                        balance(1L, "2026-07-01", "10", "20"),
                        balance(2L, "2026-07-01", "30", "50"),
                        balance(3L, "2026-07-01", "100", "200")
                ));

        ReportDtos.ReportRow row = reportService.daily(LocalDate.of(2026, 7, 1), LocalDate.of(2026, 7, 1),
                List.of(11L), null, List.of(1L, 2L), null, true, true).rows().getFirst();

        assertThat(row.openingBalance()).isEqualByComparingTo("40");
        assertThat(row.closingBalance()).isEqualByComparingTo("70");
        verify(accessService).requireAccess(List.of(11L));
        verify(accessService, times(2)).requireAccess(11L);
    }

    @Test
    void selectedLinesMustBelongToTheSelectedCompanies() {
        OperatorAccount line = account(3L, 12L, "USDT");
        when(accountRepository.findAllById(any())).thenReturn(List.of(line));

        assertThatThrownBy(() -> reportService.daily(LocalDate.of(2026, 7, 1), LocalDate.of(2026, 7, 1),
                List.of(11L), null, List.of(3L), null, true, true))
                .isInstanceOf(ApiException.class)
                .extracting(error -> ((ApiException) error).getCode())
                .isEqualTo("ACCOUNT_OUTSIDE_OPERATOR_SELECTION");
        verify(accessService).requireAccess(List.of(11L));
        verify(accessService).requireAccess(12L);
    }

    @Test
    void legacySingleAccountIdFilterRemainsSupported() {
        OperatorAccount line = account(7L, 11L, "USDC");
        when(accountRepository.findAllById(any())).thenReturn(List.of(line));
        when(balanceRepository.findByOperatorAccountIdInAndBusinessDateLessThanEqualOrderByBusinessDateAsc(
                anyList(), eq(LocalDate.of(2026, 7, 1))))
                .thenReturn(List.of(balance(7L, "2026-07-01", "2", "5")));

        ReportDtos.ReportRow row = reportService.daily(LocalDate.of(2026, 7, 1), LocalDate.of(2026, 7, 1),
                null, 7L, null, true, true).rows().getFirst();

        assertThat(row.openingBalance()).isEqualByComparingTo("2");
        assertThat(row.closingBalance()).isEqualByComparingTo("5");
        verify(accessService).requireAccess(11L);
    }

    private static OperatorAccount account(long id, long operatorId, String asset) {
        OperatorAccount account = new OperatorAccount();
        account.setId(id);
        account.setOperatorId(operatorId);
        account.setAsset(asset);
        return account;
    }

    private static DailyBalance balance(long accountId, String date, String opening, String closing) {
        DailyBalance balance = new DailyBalance();
        balance.setOperatorAccountId(accountId);
        balance.setBusinessDate(LocalDate.parse(date));
        balance.setOpeningBalance(new BigDecimal(opening));
        balance.setClosingBalance(new BigDecimal(closing));
        return balance;
    }
}
