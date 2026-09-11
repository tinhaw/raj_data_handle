package com.rajads.erp.redemption;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.audit.AuditService;
import com.rajads.erp.config.RemoteOperationGate;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.shared.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Instant;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * Executes each destructive remote step independently. Only authentication failures refresh their login session and
 * replay the same request once; all other failures stay visibly failed until an operator consciously retries them.
 */
@Service
@RequiredArgsConstructor
public class RedemptionRemoteOperationService {
    private static final ZoneId INDIA_TIME_ZONE = ZoneId.of("Asia/Kolkata");
    private static final DateTimeFormatter INDIA_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private final RedemptionCodeIssueRepository issueRepository;
    private final RedemptionCodeBatchRepository batchRepository;
    private final RedemptionRemoteConnectionService remoteConnectionService;
    private final RedemptionRemoteDirectory remoteDirectory;
    private final RemoteGiftCodeBackendClient remoteClient;
    private final ObjectProvider<UnifiedRedemptionRemoteExecutorClient> unifiedRemoteExecutorClient;
    private final ObjectMapper objectMapper;
    private final CurrentUser currentUser;
    private final AuditService auditService;
    private final PlatformTransactionManager transactionManager;
    private final RemoteOperationGate remoteOperationGate;
    private final RedemptionCodeStorage codeStorage;

    public Long createConfiguration(Long issueId, boolean retryFailed) {
        // A successful remote response must never be followed by another create POST
        // merely because our registration transaction failed.
        Long recovered = tx().execute(status -> retryRegistration(issueId, retryFailed));
        if (recovered != null) return recovered;
        UnifiedRedemptionRemoteExecutorClient executor = unifiedRemoteExecutorClient.getIfAvailable();
        if (executor != null) return createThroughUnifiedExecutor(issueId, retryFailed, executor);
        return createThroughStandaloneClient(issueId, retryFailed);
    }

    /**
     * Production compatibility mode never reaches {@link RemoteGiftCodeBackendClient}.
     * The main API resolves the compatibility account projection and owns the
     * credential decryption and remote HTTP call.
     */
    private Long createThroughUnifiedExecutor(Long issueId, boolean retryFailed, UnifiedRedemptionRemoteExecutorClient executor) {
        RemoteTaskContext context = required(tx().execute(status -> reserveCreate(issueId, retryFailed)));
        String receivedId = null;
        String receivedGroupKey = null;
        try {
            UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration created = executor.create(
                    context.account().id(), issueId, context.description(), context.claimDate(), context.validFrom(), context.validTo(), context.labelIds(),
                    context.bonusMin(), context.bonusMax(), context.options());
            receivedId = created.configurationId();
            receivedGroupKey = created.groupKey();
            return required(tx().execute(status -> completeCreate(
                    issueId, created.configurationId(), created.groupKey(), null)));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            recordCreateFailure(issueId, error, receivedId, receivedGroupKey);
            if (exception instanceof ApiException apiException) throw apiException;
            throw ApiException.badRequest("REMOTE_CREATE_FAILED", error);
        }
    }

    /** Retained solely for the isolated standalone regression fixture. */
    private Long createThroughStandaloneClient(Long issueId, boolean retryFailed) {
        try {
            remoteOperationGate.requireEnabled("remote_create");
        } catch (ApiException exception) {
            // The remote gate runs before a request can be reserved.  Without
            // persisting that rejection, the issue would remain
            // PENDING_CREATION and the operator-facing task would falsely look
            // as if it were still generating forever.
            String error = limit(exception.getMessage());
            tx().executeWithoutResult(status -> failBlockedCreate(issueId, error));
            throw exception;
        }
        RemoteTaskContext context = required(tx().execute(status -> reserveCreate(issueId, retryFailed)));
        String receivedId = null;
        String receivedGroupKey = null;
        try {
            RemoteGiftCodeBackendClient.CreatedConfiguration created = remoteClient.create(requireEnabledConnection(requireBatch(context.batchId())),
                    new RemoteGiftCodeBackendClient.CreateConfigurationRequest(context.description(), context.labelIds(), context.allUsers(),
                            context.bonusMin(), context.bonusMax(), context.claimDate(), context.validFrom(), context.validTo(), context.options()));
            receivedId = created.configurationId();
            String groupKey = null;
            String lookupError = null;
            try {
                groupKey = remoteClient.findGroupKey(requireEnabledConnection(requireBatch(context.batchId())), created.configurationId(), context.description());
                if (groupKey == null) lookupError = "远端配置已创建，暂未读到兑换组 group_key；下载时会再次查询";
            } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
                lookupError = "远端配置已创建，但暂未查询到兑换组 group_key：" + limit(exception.getMessage());
            }
            final String finalGroupKey = groupKey;
            receivedGroupKey = groupKey;
            final String finalLookupError = lookupError;
            return required(tx().execute(status -> completeCreate(issueId, created.configurationId(), finalGroupKey, finalLookupError)));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            recordCreateFailure(issueId, error, receivedId, receivedGroupKey);
            if (exception instanceof ApiException apiException) throw apiException;
            throw ApiException.badRequest("REMOTE_CREATE_FAILED", error);
        }
    }

    public Long publish(Long batchId, RedemptionDtos.RemotePublishRequest request) {
        UnifiedRedemptionRemoteExecutorClient executor = unifiedRemoteExecutorClient.getIfAvailable();
        if (executor != null) return publishThroughUnifiedExecutor(batchId, request, executor);
        return publishThroughStandaloneClient(batchId, request);
    }

    private Long publishThroughUnifiedExecutor(
            Long batchId,
            RedemptionDtos.RemotePublishRequest request,
            UnifiedRedemptionRemoteExecutorClient executor) {
        RemoteBatchContext context = required(tx().execute(status -> reservePublish(batchId, request)));
        try {
            UnifiedRedemptionRemoteExecutorClient.PublishedBatch published = executor.publish(
                    context.accountId(), batchId, context.options().publishEnvironment(), context.scheduled(),
                    context.scheduledTime(), context.fallbackToScheduled());
            return required(tx().execute(status -> completePublish(
                    batchId, published.taskId(), context.scheduled(), context.scheduledTime(), context.note())));
        } catch (ApiException exception) {
            if (!context.scheduled() && context.fallbackToScheduled()) {
                return scheduleFallbackThroughUnifiedExecutor(batchId, context, exception.getMessage(), executor);
            }
            String error = limit(exception.getMessage());
            String note = context.scheduled() ? "人工定时发布失败：" + error : "立即发布失败（未开启自动回退）：" + error;
            tx().executeWithoutResult(status -> failPublish(batchId, context.scheduled() ? "SCHEDULED" : "IMMEDIATE", context.scheduledTime(), note, error));
            throw exception;
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            String note = "远端发布状态未知，已解除本地发布占位；请先在远端管理后台核对后再选择发布方式：" + error;
            tx().executeWithoutResult(status -> failPublish(batchId, context.scheduled() ? "SCHEDULED" : "IMMEDIATE", context.scheduledTime(), note, error));
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        }
    }

    /** Retained solely for the isolated standalone regression fixture. */
    private Long publishThroughStandaloneClient(Long batchId, RedemptionDtos.RemotePublishRequest request) {
        remoteOperationGate.requireEnabled("remote_publish");
        RedemptionRemoteConnection connection = requireEnabledConnection(requireBatch(batchId));
        RemoteBatchContext context = required(tx().execute(status -> reservePublish(batchId, request)));
        try {
            String publishTaskId = remoteClient.publishAll(
                    connection, context.options().publishEnvironment(), context.scheduled(), context.scheduledTime());
            return required(tx().execute(status -> completePublish(
                    batchId, publishTaskId, context.scheduled(), context.scheduledTime(), context.note())));
        } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
            if (!context.scheduled() && context.fallbackToScheduled()) {
                return scheduleFallback(batchId, context, connection, exception.getMessage());
            }
            String error = limit(exception.getMessage());
            String note = context.scheduled() ? "人工定时发布失败：" + error : "立即发布失败（未开启自动回退）：" + error;
            tx().executeWithoutResult(status -> failPublish(batchId, context.scheduled() ? "SCHEDULED" : "IMMEDIATE", context.scheduledTime(), note, error));
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            String note = "远端发布状态未知，已解除本地发布占位；请先在远端管理后台核对后再选择发布方式：" + error;
            tx().executeWithoutResult(status -> failPublish(batchId, context.scheduled() ? "SCHEDULED" : "IMMEDIATE", context.scheduledTime(), note, error));
            if (exception instanceof ApiException apiException) throw apiException;
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        }
    }

    /**
     * Clears an abandoned local reservation only. It deliberately does not issue another remote request because the
     * outcome of the original request is unknown to this service.
     */
    public Long recoverPublishReservation(Long batchId, Long rowVersion) {
        return required(tx().execute(status -> {
            RedemptionCodeBatch batch = requireBatch(batchId);
            if (rowVersion == null || !Objects.equals(batch.getRowVersion(), rowVersion)) {
                throw ApiException.conflict("BATCH_VERSION_CONFLICT", "批次已被其他人修改，请刷新后重试");
            }
            if (!"READY_TO_PUBLISH".equals(batch.getStatus()) || !isPendingPublishReservation(batch)) {
                throw ApiException.conflict("REMOTE_PUBLISH_RECOVERY_NOT_ALLOWED", "该批次没有可恢复的发布占位");
            }
            if (batch.getUpdatedAt().isAfter(Instant.now().minus(Duration.ofMinutes(2)))) {
                throw ApiException.conflict("REMOTE_PUBLISH_STILL_RUNNING", "该批次仍可能在执行远端发布，请等待至少 2 分钟后再恢复");
            }
            String previousReservation = batch.getRemotePublishTaskId();
            batch.setRemotePublishTaskId(null);
            batch.setRemotePublishMode(null);
            batch.setRemoteScheduledPublishAt(null);
            batch.setRemotePublishError(null);
            batch.setRemotePublishNote("已人工恢复超时的本地发布占位；上次远端发布状态未知，请先核对远端后台后再选择发布方式");
            batchRepository.save(batch);
            auditService.record("REDEMPTION_REMOTE_BATCH_PUBLISH_RESERVATION_RECOVERED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                    Map.of("previousReservation", previousReservation));
            return batchId;
        }));
    }

    public Long downloadCode(Long issueId) {
        UnifiedRedemptionRemoteExecutorClient executor = unifiedRemoteExecutorClient.getIfAvailable();
        if (executor != null) {
            DownloadContext context = required(tx().execute(status -> prepareDownload(issueId)));
            try {
                var result = executor.download(context.accountId(), issueId, context.configurationId(), context.groupKey(), context.keyNumber());
                return required(tx().execute(status -> completeDownload(issueId, result.groupKey(), String.join("\n", result.codes()))));
            } catch (RuntimeException exception) {
                tx().executeWithoutResult(status -> failDownload(issueId, limit(exception.getMessage())));
                throw exception;
            }
        }
        remoteOperationGate.requireEnabled("remote_download");
        DownloadContext context = required(tx().execute(status -> prepareDownload(issueId)));
        try {
            String groupKey = context.groupKey();
            if (groupKey == null) {
                groupKey = remoteClient.findGroupKey(context.connection(), context.configurationId(), context.description());
                if (groupKey == null) throw new RemoteGiftCodeBackendClient.RemoteGiftCodeException("远端尚未返回该配置的兑换组 group_key，请稍后再试");
            }
            String code = remoteClient.downloadCode(context.connection(), groupKey);
            final String finalGroupKey = groupKey;
            return required(tx().execute(status -> completeDownload(issueId, finalGroupKey, code)));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            tx().executeWithoutResult(status -> failDownload(issueId, error));
            if (exception instanceof ApiException apiException) throw apiException;
            throw ApiException.badRequest("REMOTE_CODE_DOWNLOAD_FAILED", error);
        }
    }

    private RemoteTaskContext reserveCreate(Long issueId, boolean retryFailed) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        if (issue.getRemoteCreateReceiptId() != null || issue.getRemoteConfigurationId() != null
                || isUnreconciledLegacyCreate(issue)) {
            throw ApiException.conflict("REMOTE_CREATE_RECONCILIATION_REQUIRED", "远端配置可能已创建，禁止重复创建；请先核对并恢复本地登记");
        }
        boolean staleCreating = retryFailed && "CREATING_REMOTE".equals(issue.getWorkflowStatus())
                && issue.getRemoteConfigurationId() == null && issue.getUpdatedAt().isBefore(Instant.now().minus(Duration.ofMinutes(2)));
        boolean retryable = retryFailed && ("FAILED".equals(issue.getWorkflowStatus()) || staleCreating);
        if (!"PENDING_CREATION".equals(issue.getWorkflowStatus()) && !retryable) {
            throw ApiException.conflict("REMOTE_CREATE_NOT_ALLOWED", "该任务当前不能创建远端兑换码配置");
        }
        RedemptionRemoteDirectory.Account account = remoteDirectory.requireEnabled(batch.getRemoteConnectionId());
        requireMatchingMarket(issue, account);
        issue.setRemoteMarketId(account.marketId());
        List<Long> labels = labelIds(issue);
        boolean allUsers = labels.isEmpty();
        issue.setWorkflowStatus("CREATING_REMOTE");
        issue.setState("PENDING");
        issue.setRemoteError(null);
        issue.setRemoteRequestId(UUID.randomUUID().toString());
        issueRepository.saveAndFlush(issue);
        LocalDate validFrom = issue.getClaimDate().plusDays(batch.getValidFromDayOffset() == null ? 0 : batch.getValidFromDayOffset());
        LocalDate validTo = issue.getClaimDate().plusDays(batch.getValidToDayOffset() == null ? 0 : batch.getValidToDayOffset());
        return new RemoteTaskContext(batch.getId(), account, remoteDescription(batch, issue), labels, allUsers,
                issue.getBonusAmount(), issue.getBonusMaxAmount(), issue.getClaimDate(), validFrom, validTo, options(batch));
    }

    private Long completeCreate(Long issueId, String configurationId, String groupKey, String warning) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        if (!"CREATING_REMOTE".equals(issue.getWorkflowStatus())) throw ApiException.conflict("REMOTE_CREATE_STATE_CHANGED", "兑换码任务状态已变化，请刷新后查看");
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        issueRepository.findByRemoteMarketIdAndRemoteConfigurationId(issue.getRemoteMarketId(), configurationId).ifPresent(other -> {
            if (!Objects.equals(other.getId(), issueId)) {
                throw ApiException.conflict("REMOTE_CONFIGURATION_ID_EXISTS", "该盘口的远端配置 ID 已登记到其他任务，请核对远端记录");
            }
        });
        issue.setRemoteConfigurationId(configurationId);
        issue.setRemoteReferenceId(configurationId);
        issue.setRemoteGroupKey(groupKey);
        issue.setWorkflowStatus("CREATED");
        issue.setState("PENDING");
        issue.setRemoteError(warning);
        issueRepository.save(issue);
        refreshBatchAfterCreation(batch);
        auditService.record("REDEMPTION_REMOTE_CONFIGURATION_CREATED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null, null,
                Map.of("batchId", batch.getId(), "remoteConfigurationId", configurationId, "hasGroupKey", groupKey != null));
        return batch.getId();
    }

    private void recordCreateFailure(Long issueId, String error, String configurationId, String groupKey) {
        tx().executeWithoutResult(status -> failCreate(issueId, error, configurationId, groupKey));
    }

    private void failCreate(Long issueId, String error, String configurationId, String groupKey) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        if ("CREATING_REMOTE".equals(issue.getWorkflowStatus())) {
            issue.setWorkflowStatus("FAILED");
            issue.setState("FAILED");
            if (configurationId != null) {
                // This receipt has no uniqueness constraint: even a conflicting ID
                // must survive so an operator can reconcile it without recreating it.
                issue.setRemoteReferenceId(configurationId);
                issue.setRemoteCreateReceiptId(configurationId);
                issue.setRemoteGroupKey(groupKey);
                issue.setRemoteError(limit("远端配置已创建（ID " + configurationId
                        + "），本地登记失败；重试仅恢复登记，不会再次创建。" + error));
            } else {
                issue.setRemoteError(error);
            }
            issueRepository.save(issue);
        }
        refreshBatchAfterCreation(batch);
        auditService.record("REDEMPTION_REMOTE_CONFIGURATION_FAILED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null, null,
                Map.of("batchId", batch.getId(), "message", error));
    }

    private Long retryRegistration(Long issueId, boolean retryFailed) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        if (!retryFailed || !"FAILED".equals(issue.getWorkflowStatus())
                || issue.getRemoteCreateReceiptId() == null || issue.getRemoteConfigurationId() != null) return null;
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        requireMatchingMarket(issue, remoteDirectory.requireEnabled(batch.getRemoteConnectionId()));
        issue.setWorkflowStatus("CREATING_REMOTE");
        return completeCreate(issueId, issue.getRemoteCreateReceiptId(), issue.getRemoteGroupKey(), null);
    }

    private void requireMatchingMarket(RedemptionCodeIssue issue, RedemptionRemoteDirectory.Account account) {
        if (account.marketId() == null || account.marketId() <= 0
                || (issue.getRemoteMarketId() != 0 && !Objects.equals(issue.getRemoteMarketId(), account.marketId()))) {
            throw ApiException.conflict("REMOTE_MARKET_CHANGED", "远端账号的盘口与任务不一致，请核对后再操作");
        }
    }

    private boolean isUnreconciledLegacyCreate(RedemptionCodeIssue issue) {
        // Old releases lost the response receipt after a local SQL collision.
        // Never infer an association from SQL text or automatically create again.
        String error = issue.getRemoteError() == null ? "" : issue.getRemoteError().toLowerCase(java.util.Locale.ROOT);
        return error.contains("remote_configuration") && (error.contains("duplicate key") || error.contains("unique constraint"));
    }

    /**
     * Records a local preflight rejection only.  The remote client has not
     * been called at this point, so retrying later cannot duplicate a remote
     * configuration solely because this state was recorded.
     */
    private void failBlockedCreate(Long issueId, String error) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        if (!"PENDING_CREATION".equals(issue.getWorkflowStatus())) return;
        issue.setWorkflowStatus("FAILED");
        issue.setState("FAILED");
        issue.setRemoteError(error);
        issueRepository.save(issue);
        refreshBatchAfterCreation(batch);
        auditService.record("REDEMPTION_REMOTE_CONFIGURATION_BLOCKED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null, null,
                Map.of("batchId", batch.getId(), "message", error));
    }

    private RemoteBatchContext reservePublish(Long batchId, RedemptionDtos.RemotePublishRequest request) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        if (request == null || request.rowVersion() == null || !Objects.equals(batch.getRowVersion(), request.rowVersion())) throw ApiException.conflict("BATCH_VERSION_CONFLICT", "批次已被其他人修改，请刷新后重试");
        if (!"READY_TO_PUBLISH".equals(batch.getStatus())) throw ApiException.conflict("BATCH_NOT_READY_TO_PUBLISH", "请先完成该批次全部远端兑换码配置创建");
        if (batch.getRemotePublishTaskId() != null) throw ApiException.conflict("REMOTE_PUBLISH_IN_PROGRESS", "该批次正在执行远端发布，请稍后刷新");
        boolean scheduled = "SCHEDULED".equals(request.mode());
        boolean fallbackToScheduled = request.fallbackToScheduled() == null || request.fallbackToScheduled();
        LocalDateTime scheduledTime = request.scheduledTime();
        if (scheduled && (scheduledTime == null || !scheduledTime.isAfter(nowInIndia()))) {
            throw ApiException.badRequest("INVALID_SCHEDULED_TIME", "定时发布时间必须晚于当前印度时间");
        }
        RedemptionRemoteDirectory.Account account = remoteDirectory.requireEnabled(batch.getRemoteConnectionId());
        for (RedemptionCodeIssue issue : issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batchId)) {
            requireMatchingMarket(issue, account);
        }
        batch.setRemotePublishTaskId("PENDING:" + UUID.randomUUID());
        batch.setRemotePublishError(null);
        batch.setRemotePublishMode(null);
        batch.setRemoteScheduledPublishAt(null);
        batch.setRemotePublishNote(null);
        batch.setRemotePublishCancelledAt(null);
        batchRepository.saveAndFlush(batch);
        return new RemoteBatchContext(account.id(), null, options(batch), scheduled, scheduledTime,
                scheduled ? "人工定时发布" : "立即发布", null, fallbackToScheduled);
    }

    private Long completePublish(Long batchId, String publishTaskId, boolean scheduled, LocalDateTime scheduledTime, String note) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        if (batch.getRemotePublishTaskId() == null || !batch.getRemotePublishTaskId().startsWith("PENDING:")) throw ApiException.conflict("REMOTE_PUBLISH_STATE_CHANGED", "发布状态已变化，请刷新后查看");
        List<RedemptionCodeIssue> issues = issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batchId);
        if (issues.size() != batch.getExpectedCodeCount() || issues.stream().anyMatch(issue -> !"CREATED".equals(issue.getWorkflowStatus()))) {
            throw ApiException.conflict("BATCH_NOT_READY_TO_PUBLISH", "该批次仍有未完成的远端配置");
        }
        if (!scheduled) { issues.forEach(issue -> issue.setWorkflowStatus("PUBLISHED")); issueRepository.saveAll(issues); }
        // The existing batch-status check only has PUBLISHED. Scheduled publication is represented by the
        // persisted publish mode and time, while code issues remain CREATED until the remote task has run.
        batch.setStatus("PUBLISHED");
        batch.setPublishedAt(Instant.now());
        batch.setPublishedBy(currentUser.require().id());
        batch.setRemotePublishTaskId(publishTaskId);
        batch.setRemotePublishError(null);
        batch.setRemotePublishMode(scheduled ? "SCHEDULED" : "IMMEDIATE");
        batch.setRemoteScheduledPublishAt(scheduledTime);
        batch.setRemotePublishNote(limitNote(note + (scheduled ? "，发布时间：" + formatIndiaTime(scheduledTime) : "")));
        batch.setRemotePublishCancelledAt(null);
        batchRepository.save(batch);
        auditService.record("REDEMPTION_REMOTE_BATCH_PUBLISHED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("remotePublishTaskId", publishTaskId, "remoteConnectionId", batch.getRemoteConnectionId()));
        return batchId;
    }

    private Long scheduleFallback(
            Long batchId,
            RemoteBatchContext context,
            RedemptionRemoteConnection connection,
            String immediateError) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        LocalDateTime now = nowInIndia();
        List<LocalDateTime> attempts = new ArrayList<>(List.of(now.plusMinutes(15), now.plusMinutes(30), now.plusMinutes(60)));
        attempts.add(batch.getClaimDateFrom().atStartOfDay());
        List<String> notes = new ArrayList<>();
        notes.add("立即发布失败：" + limitNoteError(immediateError));
        for (int index = 0; index < attempts.size(); index++) try {
            LocalDateTime scheduledTime = attempts.get(index);
            int attemptNumber = index + 1;
            if (!scheduledTime.isAfter(now)) {
                notes.add("自动回退定时发布第 " + attemptNumber + " 次（" + formatIndiaTime(scheduledTime) + "）跳过：时间已过");
                continue;
            }
            String taskId = remoteClient.publishAll(connection, context.options().publishEnvironment(), true, scheduledTime);
            notes.add("自动回退定时发布第 " + attemptNumber + " 次成功（" + formatIndiaTime(scheduledTime) + "）");
            return required(tx().execute(status -> completePublish(batchId, taskId, true, scheduledTime, String.join("；", notes))));
        } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
            notes.add("自动回退定时发布第 " + (index + 1) + " 次（" + formatIndiaTime(attempts.get(index)) + "）失败：" + limitNoteError(exception.getMessage()));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            String note = limitNote(String.join("；", notes) + "；自动回退定时发布发生异常，远端状态未知：" + error);
            tx().executeWithoutResult(status -> failPublish(batchId, "IMMEDIATE", null, note, error));
            if (exception instanceof ApiException apiException) throw apiException;
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        }
        String note = limitNote(String.join("；", notes) + "；自动定时发布均失败");
        tx().executeWithoutResult(status -> failPublish(batchId, "IMMEDIATE", null, note, limit(note)));
        throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", "立即发布及自动定时发布均失败");
    }

    private Long scheduleFallbackThroughUnifiedExecutor(
            Long batchId,
            RemoteBatchContext context,
            String immediateError,
            UnifiedRedemptionRemoteExecutorClient executor) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        LocalDateTime now = nowInIndia();
        List<LocalDateTime> attempts = new ArrayList<>(List.of(
                now.plusMinutes(15), now.plusMinutes(30), now.plusMinutes(60)));
        attempts.add(batch.getClaimDateFrom().atStartOfDay());
        List<String> notes = new ArrayList<>();
        notes.add("立即发布失败：" + limitNoteError(immediateError));
        for (int index = 0; index < attempts.size(); index++) try {
            LocalDateTime scheduledTime = attempts.get(index);
            int attemptNumber = index + 1;
            if (!scheduledTime.isAfter(now)) {
                notes.add("自动回退定时发布第 " + attemptNumber + " 次（" + formatIndiaTime(scheduledTime) + "）跳过：时间已过");
                continue;
            }
            UnifiedRedemptionRemoteExecutorClient.PublishedBatch published = executor.publish(
                    context.accountId(), batchId, context.options().publishEnvironment(), true, scheduledTime, false);
            notes.add("自动回退定时发布第 " + attemptNumber + " 次成功（" + formatIndiaTime(scheduledTime) + "）");
            return required(tx().execute(status -> completePublish(
                    batchId, published.taskId(), true, scheduledTime, String.join("；", notes))));
        } catch (ApiException exception) {
            notes.add("自动回退定时发布第 " + (index + 1) + " 次（" + formatIndiaTime(attempts.get(index)) + "）失败："
                    + limitNoteError(exception.getMessage()));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            String note = limitNote(String.join("；", notes) + "；自动回退定时发布发生异常，远端状态未知：" + error);
            tx().executeWithoutResult(status -> failPublish(batchId, "IMMEDIATE", null, note, error));
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        }
        String note = limitNote(String.join("；", notes) + "；自动定时发布均失败");
        tx().executeWithoutResult(status -> failPublish(batchId, "IMMEDIATE", null, note, limit(note)));
        throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", "立即发布及自动定时发布均失败");
    }

    public Long cancelScheduledPublish(Long batchId, Long rowVersion) {
        remoteOperationGate.requireEnabled("remote_cancel");
        RemoteBatchContext context = required(tx().execute(status -> {
            RedemptionCodeBatch batch = requireBatch(batchId);
            if (rowVersion == null || !Objects.equals(batch.getRowVersion(), rowVersion)) throw ApiException.conflict("BATCH_VERSION_CONFLICT", "批次已被其他人修改，请刷新后重试");
            if (!isCancellableScheduledPublish(batch)) throw ApiException.conflict("SCHEDULED_PUBLISH_NOT_CANCELLABLE", "定时发布时间已到或批次不是定时发布状态");
            if (batch.getRemotePublishTaskId() == null || batch.getRemotePublishTaskId().isBlank()) throw ApiException.conflict("REMOTE_PUBLISH_TASK_REQUIRED", "该定时发布缺少远端任务 ID，不能撤销");
            return new RemoteBatchContext(null, requireEnabledConnection(batch), options(batch), true,
                    batch.getRemoteScheduledPublishAt(), "", batch.getRemotePublishTaskId(), false);
        }));
        try {
            remoteClient.cancelScheduledPublish(context.connection(), context.publishTaskId());
        } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
            String error = limit(exception.getMessage());
            tx().executeWithoutResult(status -> recordCancelFailure(batchId, error));
            throw ApiException.badRequest("REMOTE_SCHEDULED_PUBLISH_CANCEL_FAILED", error);
        }
        return required(tx().execute(status -> completeCancelScheduledPublish(batchId)));
    }

    private Long completeCancelScheduledPublish(Long batchId) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        if (!isCancellableScheduledPublish(batch)) throw ApiException.conflict("SCHEDULED_PUBLISH_NOT_CANCELLABLE", "定时发布状态已变化，请刷新后重试");
        batch.setStatus("READY_TO_PUBLISH");
        batch.setRemotePublishCancelledAt(Instant.now());
        batch.setRemotePublishNote("已人工撤销定时发布，不再进行后续自动定时发布尝试");
        batch.setRemotePublishError(null);
        batch.setRemotePublishTaskId(null);
        batchRepository.save(batch);
        auditService.record("REDEMPTION_REMOTE_SCHEDULED_PUBLISH_CANCELLED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("scheduledPublishAt", formatIndiaTime(batch.getRemoteScheduledPublishAt())));
        return batchId;
    }

    private void recordCancelFailure(Long batchId, String error) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        if ("PUBLISHED".equals(batch.getStatus()) && "SCHEDULED".equals(batch.getRemotePublishMode())) {
            batch.setRemotePublishNote(limitNote("撤销定时发布失败：" + error + "；原定发布时间：" + formatIndiaTime(batch.getRemoteScheduledPublishAt())));
            batchRepository.save(batch);
        }
        auditService.record("REDEMPTION_REMOTE_SCHEDULED_PUBLISH_CANCEL_FAILED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("message", error));
    }

    private void failPublish(Long batchId, String mode, LocalDateTime scheduledTime, String note, String error) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        if (batch.getRemotePublishTaskId() != null && batch.getRemotePublishTaskId().startsWith("PENDING:")) {
            batch.setRemotePublishTaskId(null);
            batch.setRemotePublishMode(mode);
            batch.setRemoteScheduledPublishAt(scheduledTime);
            batch.setRemotePublishNote(limitNote(note));
            batch.setRemotePublishError(limit(error));
            batchRepository.save(batch);
        }
        auditService.record("REDEMPTION_REMOTE_BATCH_PUBLISH_FAILED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("message", error));
    }

    private DownloadContext prepareDownload(Long issueId) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        activateScheduledPublishIfDue(batch);
        if (!("PUBLISHED".equals(issue.getWorkflowStatus()) || "CODE_IMPORTED".equals(issue.getWorkflowStatus()))) {
            throw ApiException.conflict("REMOTE_DOWNLOAD_NOT_ALLOWED", "请先发布该远端兑换码配置");
        }
        if (issue.getRemoteConfigurationId() == null) throw ApiException.conflict("REMOTE_CONFIGURATION_ID_REQUIRED", "该任务没有远端配置 ID");
        requireMatchingMarket(issue, remoteDirectory.requireEnabled(batch.getRemoteConnectionId()));
        return new DownloadContext(batch.getId(), unifiedRemoteExecutorClient.getIfAvailable() == null ? requireEnabledConnection(batch) : null,
                issue.getRemoteConfigurationId(), issue.getRemoteGroupKey(), remoteDescription(batch, issue),
                batch.getRemoteConnectionId(), batch.getRemoteKeyNumber() == null ? 1 : batch.getRemoteKeyNumber());
    }

    /**
     * The remote publish API has no completion callback. Once its configured India-time schedule has passed, the
     * first download request advances the locally tracked issues to PUBLISHED. Any remote export error remains on
     * the affected issue, rather than claiming that the scheduled task completed successfully.
     */
    private void activateScheduledPublishIfDue(RedemptionCodeBatch batch) {
        if (!("PUBLISHED".equals(batch.getStatus()) && "SCHEDULED".equals(batch.getRemotePublishMode())
                && batch.getRemoteScheduledPublishAt() != null && !batch.getRemoteScheduledPublishAt().isAfter(nowInIndia()))) {
            return;
        }
        List<RedemptionCodeIssue> issues = issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batch.getId());
        List<RedemptionCodeIssue> createdIssues = issues.stream().filter(issue -> "CREATED".equals(issue.getWorkflowStatus())).toList();
        if (createdIssues.isEmpty()) return;
        createdIssues.forEach(issue -> issue.setWorkflowStatus("PUBLISHED"));
        issueRepository.saveAll(createdIssues);
        batch.setRemotePublishNote(appendNote(batch.getRemotePublishNote(), "已到定时发布时间，开始下载兑换码"));
        batchRepository.save(batch);
    }

    private Long completeDownload(Long issueId, String groupKey, String code) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        codeStorage.store(issue, batch, code == null ? List.of() : code.lines().toList());
        issue.setRemoteGroupKey(groupKey);
        issue.setWorkflowStatus("CODE_IMPORTED");
        issue.setState("GENERATED");
        issue.setRemoteError(null);
        issue.setGeneratedAt(Instant.now());
        issueRepository.save(issue);
        refreshBatchAfterImport(batch);
        auditService.record("REDEMPTION_REMOTE_CODE_DOWNLOADED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null, null,
                Map.of("batchId", batch.getId(), "remoteConfigurationId", issue.getRemoteConfigurationId()));
        return batch.getId();
    }

    private void failDownload(Long issueId, String error) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        if (!"CODE_IMPORTED".equals(issue.getWorkflowStatus())) {
            issue.setRemoteError(error);
            issueRepository.save(issue);
        }
        auditService.record("REDEMPTION_REMOTE_CODE_DOWNLOAD_FAILED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null, null,
                Map.of("batchId", batch.getId(), "message", error));
    }

    private void refreshBatchAfterCreation(RedemptionCodeBatch batch) {
        long created = issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "CREATED");
        batch.setStatus(created == batch.getExpectedCodeCount() ? "READY_TO_PUBLISH" : "CREATING");
        batchRepository.save(batch);
    }
    private void refreshBatchAfterImport(RedemptionCodeBatch batch) {
        long imported = issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "CODE_IMPORTED");
        if (imported == batch.getExpectedCodeCount()) batch.setStatus("COMPLETED");
        batchRepository.save(batch);
    }
    private RedemptionCodeIssue requireIssue(Long id) { return issueRepository.findById(id).orElseThrow(() -> ApiException.notFound("兑换码任务")); }
    private RedemptionCodeBatch requireBatch(Long id) { return batchRepository.findById(id).orElseThrow(() -> ApiException.notFound("兑换码批次")); }
    private RedemptionCodeBatch requireRemoteBatch(RedemptionCodeIssue issue) {
        if (issue.getBatchId() == null) throw ApiException.conflict("NOT_BATCH_TASK", "该兑换码任务不属于批次");
        RedemptionCodeBatch batch = requireBatch(issue.getBatchId());
        if (batch.getRemoteConnectionId() == null) throw ApiException.conflict("MANUAL_BATCH", "该批次为人工模式，没有绑定远端连接");
        return batch;
    }
    private RedemptionRemoteConnection requireEnabledConnection(RedemptionCodeBatch batch) {
        return remoteConnectionService.requireEnabled(batch.getRemoteConnectionId());
    }
    private RemoteCreationOptions options(RedemptionCodeBatch batch) {
        if (batch.getRemotePublishEnvironment() == null || batch.getRemoteFlowTimes() == null || batch.getRemoteCreationIntervalSeconds() == null || batch.getRemoteKeyNumber() == null
                || batch.getRemoteSingleUserLimit() == null || batch.getRemoteSingleKeyLimit() == null || batch.getRemoteRequireBindBankCard() == null
                || batch.getRemoteRequireBindPhone() == null || batch.getRemoteCheckUuid() == null || batch.getRemoteUuidRewardLimit() == null
                || batch.getRemoteCheckLoginIp() == null || batch.getRemoteLoginIpRewardLimit() == null || batch.getRemoteCheckRegisterIp() == null
                || batch.getRemoteRegisterIpRewardLimit() == null) {
            throw ApiException.conflict("REMOTE_BATCH_OPTIONS_REQUIRED", "该批次缺少远端创建参数，请重新建立批次");
        }
        return new RemoteCreationOptions(batch.getRemotePublishEnvironment(), batch.getRemoteFlowTimes(), batch.getRemoteCreationIntervalSeconds(), batch.getRemoteActivityRecharge(),
                batch.getRemoteActivityRechargeCount(), batch.getRemoteActivityId(), batch.getRemoteKeyNumber(),
                batch.getRemoteSingleUserLimit(), batch.getRemoteSingleKeyLimit(), batch.getRemoteRequireBindBankCard(),
                batch.getRemoteRequireBindPhone(), batch.getRemoteCheckUuid(), batch.getRemoteUuidRewardLimit(),
                batch.getRemoteCheckLoginIp(), batch.getRemoteLoginIpRewardLimit(), batch.getRemoteCheckRegisterIp(),
                batch.getRemoteRegisterIpRewardLimit());
    }
    private List<Long> labelIds(RedemptionCodeIssue issue) {
        try { return issue.getRemoteLabelIdsJson() == null ? List.of() : objectMapper.readValue(issue.getRemoteLabelIdsJson(), new TypeReference<List<Long>>() { }); }
        catch (JsonProcessingException exception) { return List.of(); }
    }
    /** The remote console uses the same value for {@code group_desc} and {@code remark}. */
    private String remoteDescription(RedemptionCodeBatch batch, RedemptionCodeIssue issue) {
        if (batch.getRedemptionType() == RedemptionCodeType.AGENT) {
            LocalDate effectiveDate = issue.getClaimDate().plusDays(batch.getValidFromDayOffset() == null ? 0 : batch.getValidFromDayOffset());
            String audience = labelIds(issue).isEmpty()
                    ? "全部"
                    : "存款" + issue.getMinDepositAmount().stripTrailingZeros().toPlainString();
            return "%d-%02d代理%s".formatted(effectiveDate.getMonthValue(), effectiveDate.getDayOfMonth(), audience);
        }
        if (batch.getRedemptionType() == RedemptionCodeType.PREVIOUS_DAY_DEPOSIT) {
            return "NEW-" + compactMonthDay(issue.getClaimDate()) + "存款" + issue.getMinDepositAmount().stripTrailingZeros().toPlainString();
        }
        LocalDate depositEnd = issue.getClaimDate().minusDays(1);
        LocalDate depositStart = depositEnd.minusDays(batch.getLookbackDays().longValue() - 1);
        return "NEW-" + compactMonthDay(depositStart) + "到" + compactMonthDay(depositEnd) + "存款"
                + issue.getMinDepositAmount().stripTrailingZeros().toPlainString();
    }
    private String compactMonthDay(LocalDate date) { return "%d%02d".formatted(date.getMonthValue(), date.getDayOfMonth()); }
    private LocalDateTime nowInIndia() { return LocalDateTime.now(INDIA_TIME_ZONE); }
    private String appendNote(String current, String next) { return limitNote(current == null || current.isBlank() ? next : current + "；" + next); }
    private boolean isCancellableScheduledPublish(RedemptionCodeBatch batch) {
        return "PUBLISHED".equals(batch.getStatus()) && "SCHEDULED".equals(batch.getRemotePublishMode())
                && batch.getRemoteScheduledPublishAt() != null && batch.getRemoteScheduledPublishAt().isAfter(nowInIndia());
    }
    private boolean isPendingPublishReservation(RedemptionCodeBatch batch) {
        return batch.getRemotePublishTaskId() != null && batch.getRemotePublishTaskId().startsWith("PENDING:");
    }
    private String formatIndiaTime(LocalDateTime value) { return value == null ? "—" : value.format(INDIA_TIME); }
    private String limit(String value) { String safe = value == null || value.isBlank() ? "远端管理后台请求失败" : value.trim(); return safe.length() <= 900 ? safe : safe.substring(0, 900); }
    private String limitNoteError(String value) { String safe = limit(value); return safe.length() <= 300 ? safe : safe.substring(0, 300); }
    private String limitNote(String value) { String safe = value == null || value.isBlank() ? "远端管理后台请求失败" : value.trim(); return safe.length() <= 1_900 ? safe : safe.substring(0, 1_900); }
    private TransactionTemplate tx() { return new TransactionTemplate(transactionManager); }
    private <T> T required(T value) { return Objects.requireNonNull(value); }

    private record RemoteTaskContext(Long batchId, RedemptionRemoteDirectory.Account account, String description, List<Long> labelIds, boolean allUsers,
                                     java.math.BigDecimal bonusMin, java.math.BigDecimal bonusMax, java.time.LocalDate claimDate,
                                     java.time.LocalDate validFrom, java.time.LocalDate validTo,
                                     RemoteCreationOptions options) { }
    private record RemoteBatchContext(Long accountId, RedemptionRemoteConnection connection, RemoteCreationOptions options, boolean scheduled,
                                      LocalDateTime scheduledTime, String note, String publishTaskId,
                                      boolean fallbackToScheduled) { }
    private record DownloadContext(Long batchId, RedemptionRemoteConnection connection, String configurationId, String groupKey,
                                   String description, Long accountId, int keyNumber) { }
}
