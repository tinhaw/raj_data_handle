package com.rajads.erp.importing;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.audit.AuditService;
import com.rajads.erp.balance.BalanceDtos;
import com.rajads.erp.balance.BalanceService;
import com.rajads.erp.balance.DailyBalance;
import com.rajads.erp.balance.DailyBalanceRepository;
import com.rajads.erp.config.ErpProperties;
import com.rajads.erp.identity.AuthUser;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.identity.OperatorAccessService;
import com.rajads.erp.operator.OperatorAccount;
import com.rajads.erp.operator.OperatorAccountRepository;
import com.rajads.erp.operator.OperatorService;
import com.rajads.erp.operator.Operator;
import com.rajads.erp.shared.ApiException;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ImportServiceTest {
    @TempDir Path storage;

    private final ImportJobRepository jobRepository = mock(ImportJobRepository.class);
    private final ImportJobRowRepository rowRepository = mock(ImportJobRowRepository.class);
    private final DailyBalanceRepository balanceRepository = mock(DailyBalanceRepository.class);
    private final BalanceService balanceService = mock(BalanceService.class);
    private final OperatorService operatorService = mock(OperatorService.class);
    private final OperatorAccountRepository accountRepository = mock(OperatorAccountRepository.class);
    private final CurrentUser currentUser = mock(CurrentUser.class);
    private final OperatorAccessService accessService = mock(OperatorAccessService.class);
    private final AuditService auditService = mock(AuditService.class);
    private ImportService service;

    @BeforeEach
    void setUp() {
        ErpProperties properties = new ErpProperties(new ErpProperties.Storage(storage.toString()),
                new ErpProperties.BootstrapAdmin("admin", "admin123"), "Asia/Shanghai", new ErpProperties.ImportSettings(20_000), null);
        service = new ImportService(jobRepository, rowRepository, balanceRepository, balanceService, operatorService,
                accountRepository, currentUser, accessService, auditService, new ObjectMapper().findAndRegisterModules(), properties);
    }

    @Test
    void historyListsOnlyOwnJobsWhenUserDoesNotHaveAllOperatorAccess() {
        when(currentUser.require()).thenReturn(user(7L));
        when(accessService.hasAllOperators()).thenReturn(false);
        when(jobRepository.findByCreatedByOrderByCreatedAtDesc(7L)).thenReturn(List.of(job(3L, 7L, "new.xlsx", "new-hash")));

        List<ImportDtos.ImportJobResponse> jobs = service.list();

        assertThat(jobs).singleElement().satisfies(job -> {
            assertThat(job.id()).isEqualTo(3L);
            assertThat(job.createdBy()).isEqualTo(7L);
            assertThat(job.fileSha256()).isEqualTo("new-hash");
        });
        verify(jobRepository).findByCreatedByOrderByCreatedAtDesc(7L);
        verify(jobRepository, never()).findAllByOrderByCreatedAtDesc();
    }

    @Test
    void historyListsAllJobsWhenUserHasAllOperatorAccess() {
        when(currentUser.require()).thenReturn(user(7L));
        when(accessService.hasAllOperators()).thenReturn(true);
        when(jobRepository.findAllByOrderByCreatedAtDesc()).thenReturn(List.of(job(4L, 9L, "new.xlsx", "hash-2"), job(3L, 7L, "old.xlsx", "hash-1")));

        assertThat(service.list()).extracting(ImportDtos.ImportJobResponse::id).containsExactly(4L, 3L);

        verify(jobRepository).findAllByOrderByCreatedAtDesc();
        verify(jobRepository, never()).findByCreatedByOrderByCreatedAtDesc(7L);
    }

    @Test
    void templateAndErrorReportAreXlsxAndEscapeFormulaLikeInput() throws Exception {
        ImportService.XlsxDownload template = service.template();
        assertThat(template.filename()).isEqualTo("daily-balance-import-template.xlsx");
        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(template.content()))) {
            assertThat(workbook.getSheet("导入数据").getRow(0).getCell(0).getStringCellValue()).isEqualTo("业务日期");
            assertThat(workbook.getSheet("导入数据").getRow(0).getCell(1).getStringCellValue()).isEqualTo("投放公司");
            assertThat(workbook.getSheet("导入数据").getRow(0).getCell(2).getStringCellValue()).isEqualTo("投放线");
        }

        ImportJob job = job(3L, 7L, "source.xlsx", "hash");
        ImportJobRow issue = new ImportJobRow();
        issue.setSourceSheet("=sheet");
        issue.setSourceRow(2);
        issue.setOperatorName("@operator");
        issue.setOperatorAccountId(20L);
        issue.setSeverity("ERROR");
        issue.setErrorCode("IMPORT_CELL_INVALID_AMOUNT");
        issue.setErrorMessage("+bad input");
        issue.setSourceJson("=2+2");
        when(currentUser.require()).thenReturn(user(7L));
        when(accessService.hasAllOperators()).thenReturn(false);
        when(accessService.accessibleOperatorIds()).thenReturn(Set.of(100L));
        when(jobRepository.findById(3L)).thenReturn(Optional.of(job));
        when(rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(3L)).thenReturn(List.of(issue));
        when(accountRepository.findAllById(any())).thenReturn(List.of(account(20L, 100L)));

        ImportService.XlsxDownload report = service.errorReport(3L);
        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(report.content()))) {
            assertThat(workbook.getSheet("异常行").getRow(0).getCell(2).getStringCellValue()).isEqualTo("投放公司");
            assertThat(workbook.getSheet("异常行").getRow(0).getCell(3).getStringCellValue()).isEqualTo("投放线 ID");
            var row = workbook.getSheet("异常行").getRow(1);
            assertThat(row.getCell(0).getStringCellValue()).isEqualTo("'=sheet");
            assertThat(row.getCell(2).getStringCellValue()).isEqualTo("'@operator");
            assertThat(row.getCell(7).getStringCellValue()).isEqualTo("'+bad input");
            assertThat(row.getCell(9).getStringCellValue()).isEqualTo("'=2+2");
        }
    }

    @Test
    void sourceDownloadUsesStoredFileAndSanitizesDownloadFilename() throws Exception {
        ImportJob job = job(3L, 7L, "report\r\n.xlsx", "hash");
        when(currentUser.require()).thenReturn(user(7L));
        when(jobRepository.findById(3L)).thenReturn(Optional.of(job));
        Path source = storage.resolve("imports/import-3.xlsx");
        Files.createDirectories(source.getParent());
        Files.write(source, new byte[]{1, 2, 3});

        ImportService.XlsxDownload download = service.source(3L);

        assertThat(download.filename()).isEqualTo("report__.xlsx");
        assertThat(download.content()).containsExactly(1, 2, 3);
    }

    @Test
    void previewParsesReasonHeadersAndPercentageRatesAndFlagsDuplicatesInTheSameFile() {
        OperatorAccount account = account(1L, 100L);
        when(currentUser.require()).thenReturn(user(7L));
        when(operatorService.requireAccount(1L)).thenReturn(account);
        when(jobRepository.save(any(ImportJob.class))).thenAnswer(invocation -> {
            ImportJob saved = invocation.getArgument(0);
            if (saved.getId() == null) saved.setId(42L);
            return saved;
        });
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(any(), any())).thenReturn(Optional.empty());
        when(rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(42L)).thenReturn(List.of());

        String text = "日期\t汇损费率\t汇损原因\t服务费率\t服务费原因\n"
                + "2026-07-01\t2%\t汇损说明\t2%\t服务费说明\n"
                + "2026-07-01\t2%\t第二行\t2%\t第二行";
        service.previewPaste(new ImportDtos.PastePreviewRequest(text, 1L, null));

        org.mockito.ArgumentCaptor<ImportJobRow> rows = org.mockito.ArgumentCaptor.forClass(ImportJobRow.class);
        verify(rowRepository, times(2)).save(rows.capture());
        ImportJobRow first = rows.getAllValues().getFirst();
        ImportJobRow second = rows.getAllValues().get(1);
        assertThat(first.getNormalizedJson()).contains("\"exchangeLossRate\":0.02", "\"exchangeLossOverrideReason\":\"汇损说明\"",
                "\"serviceFeeRate\":0.02", "\"serviceFeeOverrideReason\":\"服务费说明\"");
        assertThat(second.getSeverity()).isEqualTo("WARNING");
        assertThat(second.getErrorCode()).isEqualTo("DUPLICATE_IN_FILE");
        assertThat(second.getAction()).isEqualTo("SKIP");
    }

    @Test
    void fixedAccountColumnPasteAcceptsManualAmountsWithoutOverrideReasons() throws Exception {
        OperatorAccount account = account(1L, 100L);
        when(currentUser.require()).thenReturn(user(7L, Set.of("IMPORT", "BALANCE_OVERRIDE")));
        when(operatorService.requireAccount(1L)).thenReturn(account);
        stubPreviewPersistence();
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(any(), any())).thenReturn(Optional.empty());

        String text = "日期\t昨日结余\t转U\t消耗\t汇损金额\t服务费金额\t回流\t退款\t其他\t其他原因\t欺诈损失\t欺诈承担方\t备注\n"
                + "2026-07-01\t100\t1000\t900\t12.5\t6.75\t7\t8\t9\t其他扣款\t100\tTRANSFER\t分列导入";
        service.previewPaste(new ImportDtos.PastePreviewRequest(text, 1L, null));

        org.mockito.ArgumentCaptor<ImportJobRow> rows = org.mockito.ArgumentCaptor.forClass(ImportJobRow.class);
        verify(rowRepository).save(rows.capture());
        String normalized = rows.getValue().getNormalizedJson();
        assertThat(normalized).contains("\"openingBalance\":100", "\"openingMode\":\"MANUAL\"",
                "\"transferAmount\":1000", "\"fraudLossAmount\":100", "\"fraudDeductionSource\":\"TRANSFER\"",
                "\"exchangeLossAmount\":12.5", "\"exchangeLossMode\":\"MANUAL\"",
                "\"serviceFeeAmount\":6.75", "\"serviceFeeMode\":\"MANUAL\"");
        BalanceDtos.DailyBalanceUpsertRequest command = new ObjectMapper().findAndRegisterModules()
                .readValue(normalized, BalanceDtos.DailyBalanceUpsertRequest.class);
        assertThat(command.openingOverrideReason()).isNull();
        assertThat(command.exchangeLossOverrideReason()).isNull();
        assertThat(command.serviceFeeOverrideReason()).isNull();
        assertThat(normalized).doesNotContain("effectiveTransferAmount", "closingBalance");
    }

    @Test
    void manualFeeImportWithoutReasonStillRequiresBalanceOverridePermission() {
        OperatorAccount account = account(1L, 100L);
        when(currentUser.require()).thenReturn(user(7L));
        when(operatorService.requireAccount(1L)).thenReturn(account);
        stubPreviewPersistence();
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(any(), any())).thenReturn(Optional.empty());

        service.previewPaste(new ImportDtos.PastePreviewRequest("日期\t汇损金额\n2026-07-01\t12.5", 1L, null));

        org.mockito.ArgumentCaptor<ImportJobRow> rows = org.mockito.ArgumentCaptor.forClass(ImportJobRow.class);
        verify(rowRepository).save(rows.capture());
        assertThat(rows.getValue().getErrorCode()).isEqualTo("FORBIDDEN");
    }

    @Test
    void previewSnapshotsExistingDraftTargetAndVersionForLaterUpdateDraftCommit() {
        OperatorAccount account = account(1L, 100L);
        DailyBalance existing = dailyBalance(10L, 3L, "DRAFT");
        when(currentUser.require()).thenReturn(user(7L));
        when(operatorService.requireAccount(1L)).thenReturn(account);
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(1L, LocalDate.of(2026, 7, 1))).thenReturn(Optional.of(existing));
        stubPreviewPersistence();

        service.previewPaste(new ImportDtos.PastePreviewRequest("日期\t转U\n2026-07-01\t100", 1L, "UPDATE_DRAFT"));

        org.mockito.ArgumentCaptor<ImportJobRow> rows = org.mockito.ArgumentCaptor.forClass(ImportJobRow.class);
        verify(rowRepository).save(rows.capture());
        assertThat(rows.getValue().getPreviewDailyBalanceId()).isEqualTo(10L);
        assertThat(rows.getValue().getPreviewRowVersion()).isEqualTo(3L);
        assertThat(rows.getValue().getErrorCode()).isEqualTo("DUPLICATE_RECORD");
    }

    @Test
    void fixedAccountPreviewRejectsInactiveAccountBeforeCreatingAJob() {
        OperatorAccount inactive = account(1L, 100L);
        inactive.setStatus("INACTIVE");
        when(operatorService.requireAccount(1L)).thenReturn(inactive);

        assertThatThrownBy(() -> service.previewPaste(new ImportDtos.PastePreviewRequest("日期\n2026-07-01", 1L, null)))
                .isInstanceOfSatisfying(ApiException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("IMPORT_ACCOUNT_INACTIVE"));
        verify(jobRepository, never()).save(any());
    }

    @Test
    void fixedAccountPreviewRejectsConflictingLegacyIdentityColumnsInsteadOfIgnoringThem() {
        OperatorAccount account = account(1L, 100L);
        Operator otherOperator = new Operator();
        otherOperator.setId(200L);
        when(currentUser.require()).thenReturn(user(7L));
        when(operatorService.requireAccount(1L)).thenReturn(account);
        when(operatorService.findAccessibleOperatorByCodeOrName("OTHER")).thenReturn(Optional.of(otherOperator));
        stubPreviewPersistence();

        String text = "日期\t运营方\t结算账户\t币种\n"
                + "2026-07-01\tOTHER\t\t\n"
                + "2026-07-02\t\tOTHER-ACCOUNT\t\n"
                + "2026-07-03\t\t\tUSDC";
        service.previewPaste(new ImportDtos.PastePreviewRequest(text, 1L, null));

        org.mockito.ArgumentCaptor<ImportJobRow> rows = org.mockito.ArgumentCaptor.forClass(ImportJobRow.class);
        verify(rowRepository, times(3)).save(rows.capture());
        assertThat(rows.getAllValues()).extracting(ImportJobRow::getErrorCode)
                .containsOnly("IMPORT_PRESET_ACCOUNT_MISMATCH");
    }

    @Test
    void fixedLinePreviewAcceptsNewDeliveryCompanyAndLineHeaders() {
        OperatorAccount line = account(1L, 100L);
        line.setName("主投放线");
        Operator company = new Operator();
        company.setId(100L);
        company.setName("星河投放");
        when(currentUser.require()).thenReturn(user(7L));
        when(operatorService.requireAccount(1L)).thenReturn(line);
        when(operatorService.findAccessibleOperatorByCodeOrName("星河投放")).thenReturn(Optional.of(company));
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(any(), any())).thenReturn(Optional.empty());
        stubPreviewPersistence();

        service.previewPaste(new ImportDtos.PastePreviewRequest(
                "业务日期\t投放公司\t投放线\t币种\t转U\n2026-07-01\t星河投放\t主投放线\tUSDT\t100", 1L, null));

        org.mockito.ArgumentCaptor<ImportJobRow> rows = org.mockito.ArgumentCaptor.forClass(ImportJobRow.class);
        verify(rowRepository).save(rows.capture());
        assertThat(rows.getValue().getErrorCode()).isNull();
        assertThat(rows.getValue().getNormalizedJson()).contains("\"transferAmount\":100");
    }

    @Test
    void excelPreviewUsesSelectedBusinessYearForYearlessDatesAndRejectsOtherYears() throws Exception {
        OperatorAccount account = account(1L, 100L);
        when(currentUser.require()).thenReturn(user(7L));
        when(operatorService.requireAccount(1L)).thenReturn(account);
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(any(), any())).thenReturn(Optional.empty());
        stubPreviewPersistence();

        MockMultipartFile file = new MockMultipartFile("file", "year.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", workbookWithDates("7月1日", "2025-07-02"));
        service.previewExcel(file, 1L, 2026, null);

        org.mockito.ArgumentCaptor<ImportJobRow> rows = org.mockito.ArgumentCaptor.forClass(ImportJobRow.class);
        verify(rowRepository, times(2)).save(rows.capture());
        assertThat(rows.getAllValues().get(0).getBusinessDate()).isEqualTo(LocalDate.of(2026, 7, 1));
        assertThat(rows.getAllValues().get(0).getErrorCode()).isNull();
        assertThat(rows.getAllValues().get(1).getErrorCode()).isEqualTo("IMPORT_DATE_OUTSIDE_BUSINESS_YEAR");
    }

    @Test
    void previewDefaultsCompactGridFraudAndOtherFieldsButStillRejectsUnsafeInput() {
        OperatorAccount account = account(1L, 100L);
        when(currentUser.require()).thenReturn(user(7L));
        when(operatorService.requireAccount(1L)).thenReturn(account);
        stubPreviewPersistence();
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(any(), any())).thenReturn(Optional.empty());

        String text = "日期\t有效转U\t期末余额\t转U\t欺诈损失\t欺诈承担方\t其他\t其他原因\t汇损金额\n"
                + "2026-07-01\t999\t999\t\t\t\t\t\t\n"
                + "2026-07-02\t\t\t100\t1\t\t\t\t\n"
                + "2026-07-03\t\t\t\t\t\t1\t\t\n"
                + "2026-07-04\t\t\t\t\t\t\t\t1\n"
                + "2026-07-05\t\t\t10\t11\t\t\t\t\n"
                + "2026-07-06\t\t\t10\t1\tUNKNOWN\t\t\t";
        service.previewPaste(new ImportDtos.PastePreviewRequest(text, 1L, null));

        org.mockito.ArgumentCaptor<ImportJobRow> rows = org.mockito.ArgumentCaptor.forClass(ImportJobRow.class);
        verify(rowRepository, times(6)).save(rows.capture());
        List<ImportJobRow> savedRows = rows.getAllValues();
        assertThat(savedRows).extracting(ImportJobRow::getErrorCode).containsExactly(
                "IMPORT_COMPUTED_FIELD_FORBIDDEN", null, null, "FORBIDDEN", "FRAUD_EXCEEDS_TRANSFER", "INVALID_FRAUD_SOURCE");
        assertThat(savedRows.get(1).getNormalizedJson()).contains("\"fraudDeductionSource\":\"TRANSFER\"");
        assertThat(savedRows.get(2).getNormalizedJson()).contains("\"otherReason\":\"批量导入\"");
    }

    @Test
    void commitRejectsStaleUpdateDraftPreviewBeforeAnyRowIsMutated() throws Exception {
        ImportJob job = job(42L, 7L, null, null);
        job.setConflictStrategy("UPDATE_DRAFT");
        ImportJobRow row = normalizedRow();
        row.setPreviewDailyBalanceId(10L);
        row.setPreviewRowVersion(1L);
        DailyBalance changed = dailyBalance(10L, 2L, "DRAFT");
        when(currentUser.require()).thenReturn(user(7L));
        when(accessService.hasAllOperators()).thenReturn(true);
        when(jobRepository.findById(42L)).thenReturn(Optional.of(job));
        when(rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(42L)).thenReturn(List.of(row));
        when(operatorService.requireAccount(1L)).thenReturn(account(1L, 100L));
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(1L, LocalDate.of(2026, 7, 1))).thenReturn(Optional.of(changed));

        assertThatThrownBy(() -> service.commit(42L, new ImportDtos.ImportCommitRequest("UPDATE_DRAFT")))
                .isInstanceOfSatisfying(ApiException.class, exception -> {
                    assertThat(exception.getCode()).isEqualTo("IMPORT_PREVIEW_STALE");
                    assertThat(exception.getStatus().value()).isEqualTo(409);
                });
        verify(balanceService, never()).createImported(any());
        verify(balanceService, never()).updateImported(any(), any(), any());
        verify(jobRepository, never()).save(any());
    }

    @Test
    void commitPassesThePreviewVersionToUpdateDraft() throws Exception {
        ImportJob job = job(42L, 7L, null, null);
        job.setConflictStrategy("UPDATE_DRAFT");
        ImportJobRow row = normalizedRow();
        row.setPreviewDailyBalanceId(10L);
        row.setPreviewRowVersion(3L);
        DailyBalance current = dailyBalance(10L, 3L, "DRAFT");
        when(currentUser.require()).thenReturn(user(7L));
        when(accessService.hasAllOperators()).thenReturn(true);
        when(jobRepository.findById(42L)).thenReturn(Optional.of(job));
        when(rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(42L)).thenReturn(List.of(row));
        when(operatorService.requireAccount(1L)).thenReturn(account(1L, 100L));
        when(balanceRepository.findByOperatorAccountIdAndBusinessDate(1L, LocalDate.of(2026, 7, 1))).thenReturn(Optional.of(current));

        ImportDtos.ImportCommitResponse response = service.commit(42L, new ImportDtos.ImportCommitRequest("UPDATE_DRAFT"));

        assertThat(response.updated()).isEqualTo(1);
        assertThat(row.getAction()).isEqualTo("UPDATED");
        verify(balanceService).updateImported(eq(10L), any(BalanceDtos.DailyBalanceUpsertRequest.class), eq(3L));
    }

    @Test
    void commitRejectsAnAccountDisabledAfterPreviewBeforeApplyingRows() throws Exception {
        ImportJob job = job(42L, 7L, null, null);
        ImportJobRow row = normalizedRow();
        OperatorAccount inactive = account(1L, 100L);
        inactive.setStatus("INACTIVE");
        when(currentUser.require()).thenReturn(user(7L));
        when(accessService.hasAllOperators()).thenReturn(true);
        when(jobRepository.findById(42L)).thenReturn(Optional.of(job));
        when(rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(42L)).thenReturn(List.of(row));
        when(operatorService.requireAccount(1L)).thenReturn(inactive);

        assertThatThrownBy(() -> service.commit(42L, new ImportDtos.ImportCommitRequest("SKIP_EXISTING")))
                .isInstanceOfSatisfying(ApiException.class,
                        exception -> assertThat(exception.getCode()).isEqualTo("IMPORT_ACCOUNT_INACTIVE"));
        verify(balanceService, never()).createImported(any());
        verify(balanceService, never()).updateImported(any(), any(), any());
    }

    @Test
    void removedOperatorScopeHidesOwnerJobAndDeniesDirectRowAccess() {
        ImportJob job = job(3L, 7L, "source.xlsx", "hash");
        ImportJobRow row = new ImportJobRow();
        row.setOperatorAccountId(20L);
        row.setSeverity("OK");
        when(currentUser.require()).thenReturn(user(7L));
        when(accessService.hasAllOperators()).thenReturn(false);
        when(accessService.accessibleOperatorIds()).thenReturn(Set.of(999L));
        when(jobRepository.findByCreatedByOrderByCreatedAtDesc(7L)).thenReturn(List.of(job));
        when(jobRepository.findById(3L)).thenReturn(Optional.of(job));
        when(rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(3L)).thenReturn(List.of(row));
        when(accountRepository.findAllById(any())).thenReturn(List.of(account(20L, 100L)));

        assertThat(service.list()).isEmpty();
        assertThatThrownBy(() -> service.rows(3L)).isInstanceOfSatisfying(ApiException.class,
                exception -> assertThat(exception.getCode()).isEqualTo("FORBIDDEN"));
        assertThatThrownBy(() -> service.get(3L)).isInstanceOfSatisfying(ApiException.class,
                exception -> assertThat(exception.getCode()).isEqualTo("FORBIDDEN"));
        assertThatThrownBy(() -> service.source(3L)).isInstanceOfSatisfying(ApiException.class,
                exception -> assertThat(exception.getCode()).isEqualTo("FORBIDDEN"));
    }

    private static ImportJob job(long id, long createdBy, String filename, String hash) {
        ImportJob job = new ImportJob();
        job.setId(id);
        job.setCreatedBy(createdBy);
        job.setSourceType("XLSX_STANDARD");
        job.setOriginalFilename(filename);
        job.setFileSha256(hash);
        job.setStatus("PREVIEW_READY");
        job.setConflictStrategy("SKIP_EXISTING");
        job.setTotalRows(1);
        job.setValidRows(1);
        job.setWarningRows(0);
        job.setErrorRows(0);
        job.setCreatedAt(Instant.parse("2026-07-01T00:00:00Z"));
        return job;
    }

    private static AuthUser user(long id) {
        return new AuthUser(id, "user" + id, "password", "测试用户", true, false, Set.of("DATA_ENTRY"), Set.of("IMPORT"));
    }

    private static AuthUser user(long id, Set<String> permissions) {
        return new AuthUser(id, "user" + id, "password", "测试用户", true, false, Set.of("DATA_ENTRY"), permissions);
    }

    private static OperatorAccount account(long id, long operatorId) {
        OperatorAccount account = new OperatorAccount();
        account.setId(id);
        account.setOperatorId(operatorId);
        account.setCode("ACCOUNT-" + id);
        account.setName("账户 " + id);
        account.setAsset("USDT");
        account.setStatus("ACTIVE");
        return account;
    }

    private void stubPreviewPersistence() {
        when(jobRepository.save(any(ImportJob.class))).thenAnswer(invocation -> {
            ImportJob saved = invocation.getArgument(0);
            if (saved.getId() == null) saved.setId(42L);
            return saved;
        });
        when(rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(42L)).thenReturn(List.of());
    }

    private static byte[] workbookWithDates(String... dates) throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            var sheet = workbook.createSheet("导入数据");
            var header = sheet.createRow(0);
            header.createCell(0).setCellValue("业务日期");
            header.createCell(1).setCellValue("转U");
            for (int index = 0; index < dates.length; index++) {
                var row = sheet.createRow(index + 1);
                row.createCell(0).setCellValue(dates[index]);
                row.createCell(1).setCellValue(100);
            }
            workbook.write(output);
            return output.toByteArray();
        }
    }

    private ImportJobRow normalizedRow() throws Exception {
        ImportJobRow row = new ImportJobRow();
        row.setImportJobId(42L);
        row.setOperatorAccountId(1L);
        row.setBusinessDate(LocalDate.of(2026, 7, 1));
        row.setSeverity("WARNING");
        row.setErrorCode("DUPLICATE_RECORD");
        row.setNormalizedJson(new ObjectMapper().findAndRegisterModules().writeValueAsString(command()));
        return row;
    }

    private static BalanceDtos.DailyBalanceUpsertRequest command() {
        return new BalanceDtos.DailyBalanceUpsertRequest(1L, LocalDate.of(2026, 7, 1), null, null, null,
                BigDecimal.ZERO, BigDecimal.ZERO, null, BigDecimal.ZERO,
                BigDecimal.ZERO, "TRANSFER", "AUTO", BigDecimal.ZERO, null,
                BigDecimal.ZERO, "SPEND", "AUTO", BigDecimal.ZERO, null,
                BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, null, 2, "IMPORT", null, null);
    }

    private static DailyBalance dailyBalance(long id, long rowVersion, String status) {
        DailyBalance balance = new DailyBalance();
        balance.setId(id);
        balance.setRowVersion(rowVersion);
        balance.setStatus(status);
        return balance;
    }
}
