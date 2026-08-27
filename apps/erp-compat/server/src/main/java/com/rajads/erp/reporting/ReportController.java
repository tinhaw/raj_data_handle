package com.rajads.erp.reporting;

import com.rajads.erp.audit.AuditService;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.time.YearMonth;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/reports")
@RequiredArgsConstructor
public class ReportController {
    private final ReportService service;
    private final ReportExcelExporter excelExporter;
    private final AuditService auditService;

    @GetMapping("/daily")
    @PreAuthorize("hasAuthority('REPORT_VIEW')")
    public ReportDtos.ReportResponse daily(@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
                                           @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
                                           @RequestParam(required = false) List<Long> operatorIds,
                                           @RequestParam(required = false) Long accountId,
                                           @RequestParam(required = false) List<Long> accountIds,
                                           @RequestParam(required = false) String asset,
                                           @RequestParam(defaultValue = "true") boolean includeDraft,
                                           @RequestParam(defaultValue = "false") boolean nominalU) {
        return service.daily(from, to, operatorIds, accountId, accountIds, asset, includeDraft, nominalU);
    }

    @GetMapping(value = "/daily/export", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('REPORT_EXPORT')")
    public void exportDaily(@RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
                            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to,
                            @RequestParam(required = false) List<Long> operatorIds,
                            @RequestParam(required = false) Long accountId,
                            @RequestParam(required = false) List<Long> accountIds,
                            @RequestParam(required = false) String asset,
                            @RequestParam(defaultValue = "true") boolean includeDraft,
                            @RequestParam(defaultValue = "false") boolean nominalU,
                            HttpServletResponse response) throws IOException {
        ReportDtos.ReportResponse report = service.daily(from, to, operatorIds, accountId, accountIds, asset, includeDraft, nominalU);
        byte[] workbook = excelExporter.export(report);
        auditExport("DAILY", from.toString(), to.toString(), operatorIds, accountId, accountIds, asset, includeDraft, nominalU, report.rows().size());
        writeWorkbook(response, "daily-report-" + from + "_to_" + to + ".xlsx", workbook);
    }

    @GetMapping("/monthly")
    @PreAuthorize("hasAuthority('REPORT_VIEW')")
    public ReportDtos.ReportResponse monthly(@RequestParam @DateTimeFormat(pattern = "yyyy-MM") YearMonth from,
                                             @RequestParam @DateTimeFormat(pattern = "yyyy-MM") YearMonth to,
                                             @RequestParam(required = false) List<Long> operatorIds,
                                             @RequestParam(required = false) Long accountId,
                                             @RequestParam(required = false) List<Long> accountIds,
                                             @RequestParam(required = false) String asset,
                                             @RequestParam(defaultValue = "true") boolean includeDraft,
                                             @RequestParam(defaultValue = "false") boolean nominalU) {
        return service.monthly(from, to, operatorIds, accountId, accountIds, asset, includeDraft, nominalU);
    }

    @GetMapping(value = "/monthly/export", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('REPORT_EXPORT')")
    public void exportMonthly(@RequestParam @DateTimeFormat(pattern = "yyyy-MM") YearMonth from,
                              @RequestParam @DateTimeFormat(pattern = "yyyy-MM") YearMonth to,
                              @RequestParam(required = false) List<Long> operatorIds,
                              @RequestParam(required = false) Long accountId,
                              @RequestParam(required = false) List<Long> accountIds,
                              @RequestParam(required = false) String asset,
                              @RequestParam(defaultValue = "true") boolean includeDraft,
                              @RequestParam(defaultValue = "false") boolean nominalU,
                              HttpServletResponse response) throws IOException {
        ReportDtos.ReportResponse report = service.monthly(from, to, operatorIds, accountId, accountIds, asset, includeDraft, nominalU);
        byte[] workbook = excelExporter.export(report);
        auditExport("MONTHLY", from.toString(), to.toString(), operatorIds, accountId, accountIds, asset, includeDraft, nominalU, report.rows().size());
        writeWorkbook(response, "monthly-report-" + from + "_to_" + to + ".xlsx", workbook);
    }

    private void auditExport(String type, String from, String to, List<Long> operatorIds, Long accountId, List<Long> accountIds, String asset,
                             boolean includeDraft, boolean nominalU, int rowCount) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("reportType", type);
        summary.put("from", from);
        summary.put("to", to);
        summary.put("operatorSelectionCount", operatorIds == null ? 0 : operatorIds.size());
        int accountSelectionCount = (accountIds == null ? 0 : (int) accountIds.stream().filter(java.util.Objects::nonNull).distinct().count())
                + (accountId == null || (accountIds != null && accountIds.contains(accountId)) ? 0 : 1);
        summary.put("accountSelected", accountSelectionCount > 0);
        summary.put("accountSelectionCount", accountSelectionCount);
        summary.put("asset", asset == null || asset.isBlank() ? "ALL" : asset.trim().toUpperCase(Locale.ROOT));
        summary.put("includeDraft", includeDraft);
        summary.put("nominalU", nominalU);
        summary.put("rowCount", rowCount);
        auditService.record("REPORT_EXPORTED", "REPORT", type, null, null, summary);
    }

    private void writeWorkbook(HttpServletResponse response, String filename, byte[] workbook) throws IOException {
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setContentLength(workbook.length);
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename(filename, StandardCharsets.UTF_8).build().toString());
        response.getOutputStream().write(workbook);
    }
}
