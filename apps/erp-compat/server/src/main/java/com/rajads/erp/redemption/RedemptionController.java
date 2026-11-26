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
    private final RedemptionDeletionService deletions;
    private final RedemptionTaskDeletionService taskDeletions;
    private final RedemptionRemoteOperationService remoteOperations;
    private final RedemptionReuseService reuseService;
    private final RedemptionDuplicateCheckService duplicateChecks;
    private final RedemptionRecoveryService recoveryService;
    private final RedemptionPolicyUpdateService policyUpdates;
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

    @PostMapping("/groups/duplicate-check")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDuplicateCheckService.Result checkDuplicates(
            @Valid @RequestBody RedemptionDuplicateCheckService.Request request) {
        return duplicateChecks.check(request);
    }

    @PostMapping("/batches/{batchId}/creation-duplicate-check")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDuplicateCheckService.Result checkPendingTaskDuplicates(@PathVariable Long batchId) {
        return duplicateChecks.checkPendingTask(batchId);
    }

    @PostMapping("/batches/{batchId}/creation-duplicate-review")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW') and hasAuthority('REDEMPTION_GENERATE')")
    public void confirmPendingTaskDuplicates(@PathVariable Long batchId,
            @Valid @RequestBody RedemptionDuplicateCheckService.Review review) {
        duplicateChecks.confirmTaskReview(batchId, review);
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

    @GetMapping("/batches/overview")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<RedemptionDtos.BatchDetailResponse> batchOverviews() { return service.batchOverviews(); }

    @GetMapping("/batches/summaries")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<RedemptionDtos.BatchSummaryResponse> batchSummaries() { return service.batchSummaries(); }

    @GetMapping("/tasks/{taskId}")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public RedemptionDtos.TaskDetailResponse taskDetail(@PathVariable Long taskId) { return service.taskDetail(taskId); }

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
                                                                         @RequestParam(defaultValue = "false") boolean retryFailed,
            @Valid @RequestBody(required=false) RedemptionDuplicateCheckService.Review review) {
        return service.batch(remoteOperations.createConfiguration(issueId, retryFailed, review));
    }

    @PostMapping("/code-tasks/{issueId}/deletion/keep-preview")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDeletionService.View previewKeep(@PathVariable Long issueId) { return deletions.previewKeep(issueId); }

    @PostMapping("/code-tasks/{issueId}/deletion/keep-confirm")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDeletionService.View confirmKeep(@PathVariable Long issueId,@RequestBody RedemptionDeletionService.KeepConfirm request) { return deletions.confirmKeep(issueId,request); }

    @PostMapping("/code-tasks/{issueId}/reuse")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse reuseExistingConfiguration(@PathVariable Long issueId,
            @Valid @RequestBody RedemptionDtos.ReuseConfigurationRequest request) {
        return service.batch(reuseService.reuse(issueId, request.rowVersion(), request.configurationId()));
    }

    @PostMapping("/code-tasks/{issueId}/recovery-check")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionRecoveryService.View inspectRecovery(@PathVariable Long issueId,
            @RequestBody RedemptionRecoveryService.InspectRequest request) {
        return recoveryService.inspect(issueId, request.rowVersion());
    }

    @PostMapping("/code-tasks/{issueId}/rebuild")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse rebuild(@PathVariable Long issueId,
            @RequestBody RedemptionRecoveryService.RebuildRequest request) {
        return service.batch(recoveryService.rebuild(issueId, request));
    }

    @PostMapping("/code-tasks/{issueId}/reward-policy/check")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionPolicyUpdateService.View checkRewardPolicy(@PathVariable Long issueId,
            @RequestBody RedemptionRecoveryService.InspectRequest request) { return policyUpdates.check(issueId, request.rowVersion()); }

    @PostMapping("/code-tasks/{issueId}/reward-policy/apply")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse applyRewardPolicy(@PathVariable Long issueId,
            @RequestBody RedemptionPolicyUpdateService.ApplyRequest request) { return service.batch(policyUpdates.apply(issueId, request)); }

    @PostMapping("/code-tasks/{issueId}/deletion/preview")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDeletionService.View deletionPreview(@PathVariable Long issueId,
            @RequestBody RedemptionRecoveryService.InspectRequest request) { return deletions.preview(issueId,request.rowVersion()); }

    @PostMapping("/code-tasks/{issueId}/deletion/confirm")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDeletionService.View deletionConfirm(@PathVariable Long issueId,
            @RequestBody RedemptionDeletionService.Confirm request) { return deletions.confirm(issueId,request); }

    @PostMapping("/code-tasks/{issueId}/deletion/reconcile")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDeletionService.View deletionReconcile(@PathVariable Long issueId) { return deletions.reconcile(issueId); }

    @GetMapping("/tasks/{taskId}/deletion")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionTaskDeletionService.View taskDeletionLatest(@PathVariable Long taskId) { return taskDeletions.latest(taskId); }

    @PostMapping("/tasks/{taskId}/deletion/preview")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionTaskDeletionService.View taskDeletionPreview(@PathVariable Long taskId, @Valid @RequestBody(required=false) RedemptionTaskDeletionService.Preview request) { return taskDeletions.preview(taskId,request); }

    @GetMapping("/tasks/{taskId}/deletion/{jobId}")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionTaskDeletionService.View taskDeletionGet(@PathVariable Long taskId,@PathVariable Long jobId) { return taskDeletions.get(taskId,jobId); }

    @PostMapping("/tasks/{taskId}/deletion/{jobId}/confirm")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionTaskDeletionService.View taskDeletionConfirm(@PathVariable Long taskId,@PathVariable Long jobId,
            @RequestBody RedemptionTaskDeletionService.Confirm request) { return taskDeletions.confirm(taskId,jobId,request); }

    @PostMapping("/tasks/{taskId}/deletion/{jobId}/next")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionTaskDeletionService.View taskDeletionNext(@PathVariable Long taskId,@PathVariable Long jobId) { return taskDeletions.next(taskId,jobId); }

    @PostMapping("/tasks/{taskId}/deletion/{jobId}/reconcile")
    @PreAuthorize("hasAuthority('REDEMPTION_MANAGE') and hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionTaskDeletionService.View taskDeletionReconcile(@PathVariable Long taskId,@PathVariable Long jobId) { return taskDeletions.reconcile(taskId,jobId); }

    @PostMapping("/code-tasks/{issueId}/remote-download")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse downloadRemoteCode(@PathVariable Long issueId, @RequestParam(defaultValue = "false") boolean withoutPublication) {
        return service.batch(remoteOperations.downloadCode(issueId, withoutPublication));
    }

    @PostMapping("/batches/{batchId}/publish")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse publish(@PathVariable Long batchId,
                                                       @RequestBody(required = false) RedemptionDtos.PublishBatchRequest request) {
        return service.markBatchPublished(batchId, request == null ? new RedemptionDtos.PublishBatchRequest(null) : request);
    }

    @PostMapping("/batches/{batchId}/remote-publish")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse publishRemote(@PathVariable Long batchId, @RequestParam(required = false) String failedTaskId,
                                                             @Valid @RequestBody RedemptionDtos.RemotePublishRequest request) {
        return service.batch(remoteOperations.publish(batchId, request, failedTaskId));
    }

    @PostMapping("/batches/{batchId}/external-publication")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse adoptExternalPublication(@PathVariable Long batchId,
            @Valid @RequestBody RedemptionDtos.ExternalPublicationRequest request) {
        return service.batch(remoteOperations.adoptExternalPublication(batchId, request));
    }

    @PostMapping("/batches/{batchId}/remote-publish/verify")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public UnifiedRedemptionRemoteExecutorClient.PublicationVerification verifyRemotePublish(@PathVariable Long batchId) {
        return remoteOperations.verifyPublication(batchId);
    }

    @PostMapping("/batches/{batchId}/missing-configurations/repair")
    @PreAuthorize("hasAuthority('REDEMPTION_GENERATE')")
    public RedemptionDtos.BatchDetailResponse startMissingConfigurationRepair(@PathVariable Long batchId,
            @RequestBody RedemptionDtos.PublishBatchRequest request) {
        return service.batch(remoteOperations.startMissingConfigurationRepair(batchId, request.rowVersion()));
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
                detail.batch().remoteMarketName(), detail.batch().redemptionType(), detail.batch().validFromDayOffset());
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

    @GetMapping(value = "/batches/{batchId}/export-available", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('REDEMPTION_EXPORT')")
    public void exportAvailable(@PathVariable Long batchId, HttpServletResponse response) throws IOException {
        RedemptionDtos.BatchDetailResponse detail = service.batch(batchId);
        if (detail.issues().stream().noneMatch(issue -> "CODE_IMPORTED".equals(issue.workflowStatus()) && !issue.redemptionCodes().isEmpty())) {
            throw com.rajads.erp.shared.ApiException.conflict("NO_IMPORTED_CODES", "当前任务没有已入库的兑换码");
        }
        byte[] workbook = excelExporter.exportAvailableOnly(detail.issues());
        auditService.record("REDEMPTION_AVAILABLE_CODES_EXPORTED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("importedCount", detail.batch().importedCount(), "expectedCount", detail.batch().expectedCodeCount()));
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setContentLength(workbook.length);
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename("redemption-codes-available-only-" + batchId + ".xlsx", StandardCharsets.UTF_8).build().toString());
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
                    detail.batch().claimDateFrom(), detail.batch().claimDateTo(), detail.batch().validFromDayOffset());
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
