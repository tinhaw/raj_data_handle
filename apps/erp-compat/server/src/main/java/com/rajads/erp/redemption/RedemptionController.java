package com.rajads.erp.redemption;

import com.rajads.erp.audit.AuditService;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/redemption-campaigns")
@RequiredArgsConstructor
public class RedemptionController {
    private final RedemptionService service;
    private final RedemptionRemoteOperationService remoteOperations;
    private final RedemptionCodeExcelExporter excelExporter;
    private final AuditService auditService;

    @GetMapping
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<RedemptionDtos.CampaignResponse> list() { return service.campaigns(); }

    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public RedemptionDtos.CampaignResponse get(@PathVariable Long id) { return service.campaign(id); }

    @PostMapping
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE')")
    public RedemptionDtos.CampaignResponse create(@Valid @RequestBody RedemptionDtos.CampaignRequest request) { return service.create(request); }

    @PostMapping("/groups")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse createCodeGroup(@Valid @RequestBody RedemptionDtos.CodeGroupCreateRequest request) {
        return service.createCodeGroup(request);
    }

    @PatchMapping("/{id}")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE')")
    public RedemptionDtos.CampaignResponse patch(@PathVariable Long id, @Valid @RequestBody RedemptionDtos.CampaignPatchRequest request) {
        return service.patch(id, request);
    }

    @GetMapping("/codes")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<RedemptionDtos.CodeIssueResponse> codes(@RequestParam Long campaignId,
                                                         @RequestParam LocalDate claimDateFrom,
                                                         @RequestParam LocalDate claimDateTo) {
        return service.issues(campaignId, claimDateFrom, claimDateTo);
    }

    @GetMapping("/batches")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<RedemptionDtos.BatchResponse> batches(@RequestParam Long campaignId) { return service.batches(campaignId); }

    @GetMapping("/batches/{batchId}")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public RedemptionDtos.BatchDetailResponse batch(@PathVariable Long batchId) { return service.batch(batchId); }

    @PostMapping("/batches")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse createManualBatch(@Valid @RequestBody RedemptionDtos.ManualBatchCreateRequest request) {
        return service.createManualBatch(request);
    }

    @PostMapping("/code-tasks/{issueId}/remote-configuration")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse recordRemoteConfiguration(@PathVariable Long issueId,
                                                                         @Valid @RequestBody RedemptionDtos.RemoteConfigurationRequest request) {
        return service.recordRemoteConfiguration(issueId, request);
    }

    @PostMapping("/code-tasks/{issueId}/remote-create")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse createRemoteConfiguration(@PathVariable Long issueId,
                                                                         @RequestParam(defaultValue = "false") boolean retryFailed) {
        return service.batch(remoteOperations.createConfiguration(issueId, retryFailed));
    }

    @PostMapping("/code-tasks/{issueId}/remote-download")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse downloadRemoteCode(@PathVariable Long issueId) {
        return service.batch(remoteOperations.downloadCode(issueId));
    }

    @PostMapping("/batches/{batchId}/publish")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse publish(@PathVariable Long batchId,
                                                       @RequestBody(required = false) RedemptionDtos.PublishBatchRequest request) {
        return service.markBatchPublished(batchId, request == null ? new RedemptionDtos.PublishBatchRequest(null) : request);
    }

    @PostMapping("/batches/{batchId}/remote-publish")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse publishRemote(@PathVariable Long batchId,
                                                             @Valid @RequestBody RedemptionDtos.RemotePublishRequest request) {
        return service.batch(remoteOperations.publish(batchId, request));
    }

    @PostMapping("/batches/{batchId}/remote-publish/cancel")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse cancelRemotePublish(@PathVariable Long batchId,
                                                                    @RequestBody(required = false) RedemptionDtos.PublishBatchRequest request) {
        return service.batch(remoteOperations.cancelScheduledPublish(batchId, request == null ? null : request.rowVersion()));
    }

    @PostMapping("/batches/{batchId}/remote-publish/recover")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse recoverRemotePublish(@PathVariable Long batchId,
                                                                     @RequestBody(required = false) RedemptionDtos.PublishBatchRequest request) {
        return service.batch(remoteOperations.recoverPublishReservation(batchId, request == null ? null : request.rowVersion()));
    }

    @PostMapping("/batches/{batchId}/codes/import")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.CodeImportResponse importCodes(@PathVariable Long batchId,
                                                          @Valid @RequestBody RedemptionDtos.CodeImportRequest request) {
        return service.importDownloadedCodes(batchId, request);
    }

    @GetMapping(value = "/batches/{batchId}/export", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('REDEMPTION_EXPORT')")
    public void exportBatch(@PathVariable Long batchId, HttpServletResponse response) throws IOException {
        RedemptionDtos.BatchDetailResponse detail = service.batch(batchId);
        RedemptionDtos.CampaignResponse campaign = service.campaign(detail.batch().campaignId());
        byte[] workbook = excelExporter.export(campaign, detail.issues(), detail.batch().claimDateFrom(), detail.batch().claimDateTo(),
                detail.batch().remoteMarketName(), detail.batch().redemptionType());
        auditService.record("REDEMPTION_BATCH_EXPORTED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("campaignCode", campaign.code(), "expectedCodeCount", detail.batch().expectedCodeCount(),
                        "importedCount", detail.batch().importedCount()));
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setContentLength(workbook.length);
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename("redemption-codes-" + exportMarketName(detail.batch().remoteMarketName()) + "-"
                        + detail.batch().claimDateFrom() + "_to_" + detail.batch().claimDateTo() + ".xlsx", StandardCharsets.UTF_8).build().toString());
        response.getOutputStream().write(workbook);
    }

    /** Downloads the batches made by one multi-market selection as separate market worksheets. */
    @GetMapping(value = "/batches/export-groups/{exportGroupKey}/export", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('REDEMPTION_EXPORT')")
    public void exportMultiMarketGroup(@PathVariable String exportGroupKey, HttpServletResponse response) throws IOException {
        List<RedemptionDtos.BatchDetailResponse> details = service.exportGroup(exportGroupKey);
        List<RedemptionCodeExcelExporter.MarketSheet> sheets = details.stream().map(detail -> {
            RedemptionDtos.CampaignResponse campaign = service.campaign(detail.batch().campaignId());
            String marketName = detail.batch().remoteMarketName();
            return new RedemptionCodeExcelExporter.MarketSheet(marketName, campaign, detail.batch().redemptionType(), detail.issues(),
                    detail.batch().claimDateFrom(), detail.batch().claimDateTo());
        }).toList();
        byte[] workbook = excelExporter.exportMultiMarket(sheets);
        RedemptionDtos.BatchResponse first = details.get(0).batch();
        auditService.record("REDEMPTION_MULTI_MARKET_EXPORTED", "REDEMPTION_CODE_BATCH_EXPORT_GROUP", exportGroupKey, null, null,
                Map.of("batchCount", details.size(), "claimDateFrom", first.claimDateFrom().toString(),
                        "claimDateTo", first.claimDateTo().toString()));
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setContentLength(workbook.length);
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename("redemption-codes-multi-market-" + first.claimDateFrom() + "_to_" + first.claimDateTo() + ".xlsx", StandardCharsets.UTF_8).build().toString());
        response.getOutputStream().write(workbook);
    }

    @GetMapping(value = "/codes/export", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('REDEMPTION_EXPORT')")
    public void export(@RequestParam Long campaignId, @RequestParam LocalDate claimDateFrom,
                       @RequestParam LocalDate claimDateTo, HttpServletResponse response) throws IOException {
        RedemptionDtos.CampaignResponse campaign = service.campaign(campaignId);
        List<RedemptionDtos.CodeIssueResponse> issues = service.issues(campaignId, claimDateFrom, claimDateTo);
        byte[] workbook = excelExporter.export(campaign, issues, claimDateFrom, claimDateTo);
        auditService.record("REDEMPTION_CODES_EXPORTED", "REDEMPTION_CAMPAIGN", campaignId.toString(), null, null,
                Map.of("campaignCode", campaign.code(), "claimDateFrom", claimDateFrom.toString(),
                        "claimDateTo", claimDateTo.toString(), "issueCount", issues.size()));
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setContentLength(workbook.length);
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename("redemption-codes-" + campaign.code() + "-" + claimDateFrom + "_to_" + claimDateTo + ".xlsx", StandardCharsets.UTF_8).build().toString());
        response.getOutputStream().write(workbook);
    }

    private String exportMarketName(String marketName) {
        if (marketName == null || marketName.isBlank()) return "unknown-market";
        String safe = marketName.trim().replaceAll("[^\\p{L}\\p{N}._ -]", "-");
        return safe.isBlank() ? "unknown-market" : safe;
    }
}
