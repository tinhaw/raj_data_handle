package com.rajads.erp.operator;

import com.rajads.erp.audit.AuditService;
import com.rajads.erp.balance.AccountingPeriodLockRepository;
import com.rajads.erp.balance.DailyBalanceRepository;
import com.rajads.erp.identity.AuthUser;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.identity.OperatorAccessService;
import com.rajads.erp.shared.ApiException;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OperatorServiceTest {
    private final OperatorRepository operatorRepository = mock(OperatorRepository.class);
    private final OperatorAccountRepository accountRepository = mock(OperatorAccountRepository.class);
    private final DailyBalanceRepository balanceRepository = mock(DailyBalanceRepository.class);
    private final AccountingPeriodLockRepository lockRepository = mock(AccountingPeriodLockRepository.class);
    private final OperatorAccessService accessService = mock(OperatorAccessService.class);
    private final CurrentUser currentUser = mock(CurrentUser.class);
    private final AuditService auditService = mock(AuditService.class);
    private final OperatorService service = new OperatorService(operatorRepository, accountRepository, balanceRepository, lockRepository, accessService, currentUser, auditService);

    OperatorServiceTest() {
        when(currentUser.require()).thenReturn(new AuthUser(9L, "admin", "", "管理员", true, false, Set.of("SUPER_ADMIN"), Set.of("*")));
    }

    @Test
    void createsDeliveryCompanyWithoutAUserSuppliedCode() {
        when(operatorRepository.findAll()).thenReturn(List.of());
        when(operatorRepository.existsByCodeIgnoreCase(anyString())).thenReturn(false);
        when(operatorRepository.save(any(Operator.class))).thenAnswer(invocation -> {
            Operator saved = invocation.getArgument(0);
            saved.setId(1L);
            return saved;
        });

        OperatorDtos.OperatorResponse response = service.create(new OperatorDtos.OperatorRequest(null, "  北极星投放  ", null, null, null, null));

        assertThat(response.name()).isEqualTo("北极星投放");
        assertThat(response.operatorType()).isEqualTo("COMPANY");
        assertThat(response.code()).startsWith("COMP-");
    }

    @Test
    void rejectsCompanyNamesIgnoringLeadingTrailingWhitespaceAndCase() {
        Operator existing = company(1L, "  Acme  ");
        when(operatorRepository.findAll()).thenReturn(List.of(existing));

        assertThatThrownBy(() -> service.create(new OperatorDtos.OperatorRequest(null, "acme", null, null, null, null)))
                .isInstanceOf(ApiException.class)
                .extracting(error -> ((ApiException) error).getCode())
                .isEqualTo("COMPANY_NAME_EXISTS");
    }

    @Test
    void preservesAnExplicitLegacyCompanyCodeForExistingIntegrations() {
        when(operatorRepository.findAll()).thenReturn(List.of());
        when(operatorRepository.existsByCodeIgnoreCase("CLIENT-A")).thenReturn(false);
        when(operatorRepository.save(any(Operator.class))).thenAnswer(invocation -> {
            Operator saved = invocation.getArgument(0);
            saved.setId(2L);
            return saved;
        });

        OperatorDtos.OperatorResponse response = service.create(new OperatorDtos.OperatorRequest(" client-a ", "北极星投放", "STUDIO", null, null, null));

        assertThat(response.code()).isEqualTo("CLIENT-A");
        assertThat(response.operatorType()).isEqualTo("STUDIO");
    }

    @Test
    void createsDeliveryLineWithUsdtByDefaultAndNormalizesUsdc() {
        Operator company = company(11L, "北极星投放");
        when(operatorRepository.findById(11L)).thenReturn(Optional.of(company));
        when(accountRepository.findByOperatorIdOrderByAssetAscCodeAsc(11L)).thenReturn(List.of());
        when(accountRepository.findFirstByOperatorIdAndCodeIgnoreCase(anyLong(), anyString())).thenReturn(Optional.empty());
        when(accountRepository.save(any(OperatorAccount.class))).thenAnswer(invocation -> {
            OperatorAccount saved = invocation.getArgument(0);
            saved.setId(101L);
            return saved;
        });

        OperatorDtos.AccountResponse usdt = service.createAccount(11L,
                new OperatorDtos.AccountRequest(null, "  主投放线 ", null, null, null, null, null, null, null, null, null));
        OperatorDtos.AccountResponse usdc = service.createAccount(11L,
                new OperatorDtos.AccountRequest(" legacy-usdc ", " USDC 备用线 ", "usdc", null, null, null, null, null, null, null, null));

        assertThat(usdt.asset()).isEqualTo("USDT");
        assertThat(usdc.asset()).isEqualTo("USDC");
        assertThat(usdc.code()).isEqualTo("LEGACY-USDC");
        assertThat(usdt.displayName()).isEqualTo("北极星投放 · 主投放线");

        ArgumentCaptor<OperatorAccount> saved = ArgumentCaptor.forClass(OperatorAccount.class);
        org.mockito.Mockito.verify(accountRepository, org.mockito.Mockito.times(2)).save(saved.capture());
        assertThat(saved.getAllValues()).allSatisfy(line -> {
            assertThat(line.getDefaultExchangeLossRate()).isEqualByComparingTo(new BigDecimal("0.02"));
            assertThat(line.getDefaultServiceFeeRate()).isEqualByComparingTo(new BigDecimal("0.02"));
        });
        assertThat(saved.getAllValues().getFirst().getCode()).startsWith("LINE-");
        assertThat(saved.getAllValues().get(1).getCode()).isEqualTo("LEGACY-USDC");
    }

    @Test
    void rejectsDuplicateLineNamesWithinTheSameCompany() {
        Operator company = company(11L, "北极星投放");
        OperatorAccount existing = new OperatorAccount();
        existing.setId(71L);
        existing.setOperatorId(11L);
        existing.setName("主投放线");
        when(operatorRepository.findById(11L)).thenReturn(Optional.of(company));
        when(accountRepository.findByOperatorIdOrderByAssetAscCodeAsc(11L)).thenReturn(List.of(existing));

        assertThatThrownBy(() -> service.createAccount(11L,
                new OperatorDtos.AccountRequest(null, " 主投放线 ", null, null, null, null, null, null, null, null, null)))
                .isInstanceOf(ApiException.class)
                .extracting(error -> ((ApiException) error).getCode())
                .isEqualTo("DELIVERY_LINE_NAME_EXISTS");
    }

    @Test
    void deletesCompanyAndItsLinesWhenThereIsNoHistoricalData() {
        Operator company = company(11L, "北极星投放");
        company.setRowVersion(3L);
        OperatorAccount firstLine = new OperatorAccount();
        firstLine.setId(101L);
        firstLine.setOperatorId(11L);
        OperatorAccount secondLine = new OperatorAccount();
        secondLine.setId(102L);
        secondLine.setOperatorId(11L);
        List<OperatorAccount> lines = List.of(firstLine, secondLine);
        when(operatorRepository.findById(11L)).thenReturn(Optional.of(company));
        when(accountRepository.findByOperatorIdOrderByAssetAscCodeAsc(11L)).thenReturn(lines);
        when(balanceRepository.countByOperatorAccountIdIn(List.of(101L, 102L))).thenReturn(0L);
        when(lockRepository.countByOperatorAccountIdIn(List.of(101L, 102L))).thenReturn(0L);

        service.delete(11L, new OperatorDtos.DeleteRequest(null, 3L, false));

        verify(accountRepository).deleteAllInBatch(lines);
        verify(operatorRepository).delete(company);
    }

    @Test
    void preventsDeletingCompanyWhenAnyLineHasHistoricalLedgerData() {
        Operator company = company(11L, "北极星投放");
        OperatorAccount line = new OperatorAccount();
        line.setId(101L);
        line.setOperatorId(11L);
        when(operatorRepository.findById(11L)).thenReturn(Optional.of(company));
        when(accountRepository.findByOperatorIdOrderByAssetAscCodeAsc(11L)).thenReturn(List.of(line));
        when(balanceRepository.countByOperatorAccountIdIn(List.of(101L))).thenReturn(1L);
        when(lockRepository.countByOperatorAccountIdIn(List.of(101L))).thenReturn(0L);

        assertThatThrownBy(() -> service.delete(11L, new OperatorDtos.DeleteRequest(null, null, false)))
                .isInstanceOf(ApiException.class)
                .extracting(error -> ((ApiException) error).getCode())
                .isEqualTo("OPERATOR_HAS_HISTORY");
    }

    @Test
    void purgesHistoricalLedgerAndLocksOnlyAfterExplicitConfirmation() {
        Operator company = company(11L, "北极星投放");
        OperatorAccount line = new OperatorAccount();
        line.setId(101L);
        line.setOperatorId(11L);
        when(operatorRepository.findById(11L)).thenReturn(Optional.of(company));
        when(accountRepository.findByOperatorIdOrderByAssetAscCodeAsc(11L)).thenReturn(List.of(line));
        when(balanceRepository.countByOperatorAccountIdIn(List.of(101L))).thenReturn(3L);
        when(lockRepository.countByOperatorAccountIdIn(List.of(101L))).thenReturn(1L);

        service.delete(11L, new OperatorDtos.DeleteRequest("用户确认清空", null, true));

        verify(balanceRepository).deleteByOperatorAccountIdIn(List.of(101L));
        verify(lockRepository).deleteByOperatorAccountIdIn(List.of(101L));
        verify(accountRepository).deleteAllInBatch(List.of(line));
        verify(operatorRepository).delete(company);
    }

    private static Operator company(Long id, String name) {
        Operator operator = new Operator();
        operator.setId(id);
        operator.setName(name);
        operator.setCode("LEGACY-" + id);
        return operator;
    }
}
