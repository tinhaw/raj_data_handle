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
    private final jakarta.persistence.EntityManager entityManager;
    private final RemoteOperationGate remoteOperationGate;
    private final RedemptionCodeStorage codeStorage;
    private final RedemptionReuseService reuseService;
    private final RedemptionDuplicateCheckService duplicateChecks;
    private final RedemptionBatchProgress batchProgress;
    private final RedemptionRecoveryRepository recoveryRepository;
    private final RedemptionPolicyUpdateService policyUpdates;

    public Long createConfiguration(Long issueId, boolean retryFailed) {
        return createConfiguration(issueId, retryFailed, null);
    }

    public Long createConfiguration(Long issueId, boolean retryFailed, RedemptionDuplicateCheckService.Review review) {
        return reuseService.withIssueLock(issueId, () -> createOrReuseConfiguration(issueId, retryFailed, review));
    }

    private Long createOrReuseConfiguration(Long issueId, boolean retryFailed, RedemptionDuplicateCheckService.Review review) {
        // A successful remote response must never be followed by another create POST
        // merely because our registration transaction failed.
        try {
            var waitingBatch = tx().execute(status -> {
                var issue = requireIssue(issueId);
                RedemptionDeletionService.requireAvailable(issue);
                return RedemptionRewardCheck.pending(issue) || issue.getReusedFromIssue() != null ? issue.getBatchId() : null;
            });
            if (waitingBatch != null) {
                policyUpdates.verifyForCreation(issueId);
                return waitingBatch;
            }
            // Creating a new configuration never silently chooses the remote reuse/check path.
            // Users may explicitly choose the existing reuse or recovery actions for local conflicts.
            duplicateChecks.requireReviewedDuplicates(issueId, review);
            Long recovered = tx().execute(status -> retryRegistration(issueId, retryFailed));
            if (recovered != null) {
                if (unifiedRemoteExecutorClient.getIfAvailable() != null) policyUpdates.verifyForCreation(issueId);
                return recovered;
            }
            UnifiedRedemptionRemoteExecutorClient executor = unifiedRemoteExecutorClient.getIfAvailable();
            if (executor != null) return createThroughUnifiedExecutor(issueId, retryFailed, executor);
            return createThroughStandaloneClient(issueId, retryFailed);
        } catch (ApiException exception) {
            if (java.util.Set.of("LOCAL_REDEMPTION_DUPLICATE", "SPECIAL_CODE_ALREADY_EXISTS", "REUSE_POLICY_MISMATCH", "REUSE_AMBIGUOUS_CONFIGURATION",
                    "REUSE_CHECK_UNAVAILABLE", "REUSE_UNCONFIRMED_CONFIGURATION", "REUSE_CONFIGURATION_IDENTITY_MISMATCH",
                    "REMOTE_REUSE_CHECK_REJECTED", "RECOVERY_CHECK_UNAVAILABLE", "REMOTE_CONFIGURATION_MISSING", "REMOTE_CONFIGURATION_RECOVERY_REQUIRED").contains(exception.getCode())) {
                tx().executeWithoutResult(status -> failBlockedCreate(issueId, exception.getMessage()));
            }
            throw exception;
        }
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
        Long batchId;
        try {
            UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration created = executor.create(
                    context.account().id(), issueId, context.description(), context.claimDate(), context.validFrom(), context.validTo(), context.labelIds(),
                    context.bonusMin(), context.bonusMax(), context.options(), context.giftCode());
            receivedId = RemoteConfigurationIds.requireCreated(created.configurationId());
            receivedGroupKey = created.groupKey();
            batchId = required(tx().execute(status -> completeCreate(
                    issueId, created.configurationId(), created.groupKey(), null)));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            recordCreateFailure(issueId, error, receivedId, receivedGroupKey);
            if (exception instanceof ApiException apiException) throw apiException;
            throw ApiException.badRequest("REMOTE_CREATE_FAILED", error);
        }
        // The receipt is durable before readback. A failed read retries only verification, never creation.
        policyUpdates.verifyForCreation(issueId);
        return batchId;
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
                            context.bonusMin(), context.bonusMax(), context.claimDate(), context.validFrom(), context.validTo(), context.options(), context.giftCode()));
            receivedId = RemoteConfigurationIds.requireCreated(created.configurationId());
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
        requirePublishReservation(batchId, context);
        try {
            UnifiedRedemptionRemoteExecutorClient.PublishedBatch published = executor.publish(
                    context.accountId(), batchId, context.options().publishEnvironment(), context.scheduled(),
                    context.scheduledTime(), context.fallbackToScheduled());
            return required(tx().execute(status -> completePublish(
                    batchId, context.publishTaskId(), published.taskId(), context.scheduled(), context.scheduledTime(), context.note())));
        } catch (ApiException exception) {
            if (!context.scheduled() && context.fallbackToScheduled()) {
                requirePublishReservation(batchId, context);
                return scheduleFallbackThroughUnifiedExecutor(batchId, context, exception.getMessage(), executor);
            }
            String error = limit(exception.getMessage());
            String note = context.scheduled() ? "人工定时发布失败：" + error : "立即发布失败（未提交定时发布）：" + error;
            tx().executeWithoutResult(status -> failPublish(batchId, context.publishTaskId(), context.scheduled() ? "SCHEDULED" : "IMMEDIATE", context.scheduledTime(), note, error));
            throw exception;
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            String note = "远端发布状态未知，已解除本地发布占位；请先在远端管理后台核对后再选择发布方式：" + error;
            tx().executeWithoutResult(status -> failPublish(batchId, context.publishTaskId(), context.scheduled() ? "SCHEDULED" : "IMMEDIATE", context.scheduledTime(), note, error));
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        }
    }

    /** Retained solely for the isolated standalone regression fixture. */
    private Long publishThroughStandaloneClient(Long batchId, RedemptionDtos.RemotePublishRequest request) {
        remoteOperationGate.requireEnabled("remote_publish");
        RedemptionRemoteConnection connection = requireEnabledConnection(requireBatch(batchId));
        RemoteBatchContext context = required(tx().execute(status -> reservePublish(batchId, request)));
        requirePublishReservation(batchId, context);
        try {
            String publishTaskId = remoteClient.publishAll(
                    connection, context.options().publishEnvironment(), context.scheduled(), context.scheduledTime());
            return required(tx().execute(status -> completePublish(
                    batchId, context.publishTaskId(), publishTaskId, context.scheduled(), context.scheduledTime(), context.note())));
        } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
            if (!context.scheduled() && context.fallbackToScheduled()) {
                return scheduleFallback(batchId, context, connection, exception.getMessage());
            }
            String error = limit(exception.getMessage());
            String note = context.scheduled() ? "人工定时发布失败：" + error : "立即发布失败（未提交定时发布）：" + error;
            tx().executeWithoutResult(status -> failPublish(batchId, context.publishTaskId(), context.scheduled() ? "SCHEDULED" : "IMMEDIATE", context.scheduledTime(), note, error));
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            String note = "远端发布状态未知，已解除本地发布占位；请先在远端管理后台核对后再选择发布方式：" + error;
            tx().executeWithoutResult(status -> failPublish(batchId, context.publishTaskId(), context.scheduled() ? "SCHEDULED" : "IMMEDIATE", context.scheduledTime(), note, error));
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
            if (!("READY_TO_PUBLISH".equals(batch.getStatus()) || isRepairing(batch)) || !isPendingPublishReservation(batch)) {
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

    public Long adoptExternalPublication(Long batchId, RedemptionDtos.ExternalPublicationRequest request) {
        var executor = unifiedRemoteExecutorClient.getIfAvailable();
        if (executor == null) throw ApiException.conflict("REMOTE_VERIFY_UNAVAILABLE", "当前环境不支持统一远端核验");
        var snapshot = required(tx().execute(status -> externalPublicationContext(batchId, request)));
        var context = snapshot.candidate();
        boolean rebind = snapshot.previousId() != null && !snapshot.previousId().startsWith("PENDING:");
        if (rebind) {
            var original = executor.verifyPublication(context.accountId(), batchId, snapshot.previousId(), context.environment(), context.configurations());
            if (!snapshot.previousId().equals(original.remotePublishTaskId()) || !("FAILED".equals(original.publicationState()) || "CANCELLED".equals(original.publicationState())))
                throw ApiException.conflict("EXTERNAL_REBIND_NOT_ALLOWED", "原系统发布未确认失败或撤销，不允许换绑");
        }
        var result = executor.verifyPublication(context.accountId(), batchId, context.taskId(),
                context.environment(), context.configurations());
        if (!context.taskId().equals(result.remotePublishTaskId()) || !java.util.Set.of("WAITING", "RUNNING", "COMPLETED").contains(result.publicationState())) {
            throw ApiException.conflict("EXTERNAL_PUBLICATION_NOT_ACTIVE", "未查到可关联的发布任务，请核对任务 ID、盘口及发布环境");
        }
        var matched = result.configurations().stream().filter(item -> "MATCHED".equals(item.state()))
                .map(UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification::configurationId)
                .collect(java.util.stream.Collectors.toSet());
        if (rebind && !"COMPLETED".equals(result.publicationState()))
            throw ApiException.conflict("EXTERNAL_REPLACEMENT_NOT_COMPLETED", "换绑前须确认新发布已完成且配置匹配");
        if ("COMPLETED".equals(result.publicationState()) && (result.configurationError() != null || context.configurations().stream()
                .anyMatch(ref -> !matched.contains(ref.configuration_id())))) {
            throw ApiException.conflict("EXTERNAL_CONFIGURATION_MISMATCH", "远端发布已完成，但本批次配置未全部匹配，请核对配置后重试");
        }
        return required(tx().execute(status -> {
            var latest = externalPublicationContext(batchId, request);
            if (!snapshot.equals(latest)) throw ApiException.conflict("REMOTE_PUBLISH_STATE_CHANGED", "原任务、配置或账号已变化，请刷新后重新核验");
            var batch = requireBatch(batchId);
            batch.setRemotePublishTaskId(context.taskId());
            batch.setRemotePublishMode("EXTERNAL");
            batch.setRemoteScheduledPublishAt(null);
            batch.setRemotePublishCancelledAt(null);
            batch.setRemotePublishError(null);
            batch.setStatus("PUBLISHED");
            batch.setPublishedAt(Instant.now());
            batch.setPublishedBy(currentUser.require().id());
            batch.setRemotePublishNote(appendNote(batch.getRemotePublishNote(), "手动发布任务 " + context.taskId() + " 已关联；远端状态：" + result.publicationState()));
            batchRepository.save(batch);
            auditService.record("REDEMPTION_EXTERNAL_PUBLICATION_VERIFIED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                    Map.of("remotePublishTaskId", context.taskId(), "previousRemotePublishTaskId", Objects.toString(snapshot.previousId(), ""), "remoteConnectionId", context.accountId(),
                            "configurationCount", context.configurations().size(), "checkedAt", result.checkedAt()));
            return batchId;
        }));
    }

    private record ExternalPublicationSnapshot(String previousId, VerificationContext candidate) { }

    private ExternalPublicationSnapshot externalPublicationContext(Long batchId, RedemptionDtos.ExternalPublicationRequest request) {
        var batch = requireFreshBatch(batchId);
        issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batchId).forEach(RedemptionRewardCheck::requireReady);
        if (!Objects.equals(request.rowVersion(), batch.getRowVersion()))
            throw ApiException.conflict("BATCH_VERSION_CONFLICT", "批次已变化，请刷新后重试");
        String previousId = batch.getRemotePublishTaskId();
        boolean rebind = "PUBLISHED".equals(batch.getStatus()) && previousId != null && !previousId.isBlank()
                && !isPendingPublishReservation(batch) && !previousId.equals(request.remotePublishTaskId())
                && ("SCHEDULED".equals(batch.getRemotePublishMode()) || "IMMEDIATE".equals(batch.getRemotePublishMode()));
        if (!rebind && !("READY_TO_PUBLISH".equals(batch.getStatus()) && (previousId == null || isPendingPublishReservation(batch))))
            throw ApiException.conflict("EXTERNAL_PUBLICATION_NOT_ALLOWED", "仅允许未取得发布 ID 的批次回填，或在原系统发布确认失败或撤销后换绑");
        var account = remoteDirectory.requireEnabled(batch.getRemoteConnectionId());
        List<UnifiedRedemptionRemoteExecutorClient.ConfigurationReference> refs = new ArrayList<>();
        for (var issue : canonicalIssues(batchId)) {
            entityManager.refresh(issue);
            RedemptionDeletionService.requireAvailable(issue);
            requireMatchingMarket(issue, account);
            RemoteConfigurationIds.requireUsable(issue);
            if (!("CREATED".equals(issue.getWorkflowStatus()) || rebind && "PUBLISHED".equals(issue.getWorkflowStatus())) || issue.getRemoteConfigurationId() == null
                    || issue.getRemoteGroupKey() == null || issue.getRemoteGroupKey().isBlank())
                throw ApiException.conflict("EXTERNAL_CONFIGURATION_NOT_READY", "请先完成所有配置创建并确认兑换码组标识");
            refs.add(new UnifiedRedemptionRemoteExecutorClient.ConfigurationReference(issue.getRemoteConfigurationId(),
                    issue.getRemoteGroupKey(), effectiveKeyNumber(issue, batch)));
        }
        if (refs.isEmpty()) throw ApiException.conflict("EXTERNAL_CONFIGURATION_NOT_READY", "当前批次没有可核验的配置");
        return new ExternalPublicationSnapshot(previousId, new VerificationContext(account.id(), request.remotePublishTaskId(), options(batch).publishEnvironment(), List.copyOf(refs)));
    }

    public UnifiedRedemptionRemoteExecutorClient.PublicationVerification verifyPublication(Long batchId) {
        var executor = unifiedRemoteExecutorClient.getIfAvailable();
        if (executor == null) throw ApiException.conflict("REMOTE_VERIFY_UNAVAILABLE", "当前环境不支持统一远端核验");
        var context = required(tx().execute(status -> {
            RedemptionCodeBatch batch = requireBatch(batchId);
            if (!java.util.Set.of("PUBLISHED", "COMPLETED").contains(batch.getStatus())
                    || batch.getRemotePublishTaskId() == null || batch.getRemotePublishTaskId().startsWith("PENDING:")) {
                throw ApiException.conflict("REMOTE_VERIFY_NOT_ALLOWED", "当前批次没有可核验的远端发布任务");
            }
            var account = remoteDirectory.requireEnabled(batch.getRemoteConnectionId());
            List<UnifiedRedemptionRemoteExecutorClient.ConfigurationReference> refs = new ArrayList<>();
            for (var issue : canonicalIssues(batchId)) {
                requireMatchingMarket(issue, account);
                RemoteConfigurationIds.requireUsable(issue);
                if (issue.getRemoteConfigurationId() == null) throw ApiException.conflict("REMOTE_CONFIGURATION_ID_REQUIRED", "配置标识缺失，请先核对任务");
                refs.add(new UnifiedRedemptionRemoteExecutorClient.ConfigurationReference(issue.getRemoteConfigurationId(),
                        issue.getRemoteGroupKey(), effectiveKeyNumber(issue, batch)));
            }
            return new VerificationContext(account.id(), batch.getRemotePublishTaskId(), options(batch).publishEnvironment(), refs);
        }));
        var result = executor.verifyPublication(context.accountId(), batchId, context.taskId(), context.environment(), context.configurations());
        tx().executeWithoutResult(status -> {
            var batch = requireFreshBatch(batchId);
            if (!context.taskId().equals(batch.getRemotePublishTaskId()) || !context.accountId().equals(batch.getRemoteConnectionId())) {
                throw ApiException.conflict("REMOTE_PUBLISH_STATE_CHANGED", "发布任务已变化，请刷新后重新核验");
            }
            auditService.record("REDEMPTION_REMOTE_PUBLICATION_VERIFIED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null, result);
        });
        return result;
    }

    /** Starts an explicit repair only for configurations freshly confirmed absent from the remote directory. */
    public Long startMissingConfigurationRepair(Long batchId, Long rowVersion) {
        var verification = verifyPublication(batchId);
        if (!"COMPLETED".equals(verification.publicationState()) || verification.configurationError() != null) {
            throw ApiException.conflict("REMOTE_REPAIR_VERIFY_REQUIRED", "远端发布或配置列表尚未核验完成，不能重建配置");
        }
        return required(tx().execute(status -> {
            var batch = requireFreshBatch(batchId);
            if (rowVersion == null || !Objects.equals(rowVersion, batch.getRowVersion()))
                throw ApiException.conflict("BATCH_VERSION_CONFLICT", "批次已变化，请刷新核验结果后重试");
            if (!"PUBLISHED".equals(batch.getStatus()) || !Objects.equals(batch.getRemotePublishTaskId(), verification.remotePublishTaskId()))
                throw ApiException.conflict("REMOTE_REPAIR_STATE_CHANGED", "发布任务已变化，请刷新后重试");
            var missingIds = verification.configurations().stream()
                    .filter(item -> "MISSING".equals(item.state())).map(UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification::configurationId)
                    .collect(java.util.stream.Collectors.toSet());
            if (missingIds.isEmpty()) throw ApiException.conflict("REMOTE_REPAIR_NOT_NEEDED", "远端没有缺失的配置");
            var issues = canonicalIssues(batchId);
            var missing = issues.stream().filter(issue -> missingIds.contains(issue.getRemoteConfigurationId())
                    && !"CODE_IMPORTED".equals(issue.getWorkflowStatus())).toList();
            if (missing.size() != missingIds.size()) throw ApiException.conflict("REMOTE_REPAIR_ISSUES_CHANGED", "缺失配置与当前任务不一致，请重新核验");
            for (var issue : missing) {
                if (issueRepository.existsByReusedFromIssueId(issue.getId())) throw ApiException.conflict("SHARED_CONFIGURATION_LOCKED", "该配置已被其他任务复用，不能单独重建身份");
                var oldId = issue.getRemoteConfigurationId();
                issue.setRemoteReferenceId(oldId);
                issue.setRemoteConfigurationId(null);
                issue.setRemoteGroupKey(null);
                issue.setWorkflowStatus("PENDING_CREATION");
                issue.setState("PENDING");
                issue.setRemoteError("原配置 " + oldId + " 经远端核验不存在，等待重建");
                auditService.record("REDEMPTION_MISSING_CONFIGURATION_REPAIR_STARTED", "REDEMPTION_CODE_ISSUE", issue.getId().toString(), null, null,
                        Map.of("batchId", batchId, "previousConfigurationId", oldId,
                                "configurationName", remoteDescription(batch, issue)));
            }
            issueRepository.saveAll(issues);
            batch.setStatus("CREATING");
            batch.setRemotePublishNote(appendNote(batch.getRemotePublishNote(), "缺失配置重建中；原发布任务不再用于新配置下载"));
            batchRepository.save(batch);
            return batchId;
        }));
    }

    private RedemptionCodeBatch requireFreshBatch(Long batchId) {
        var batch = requireBatch(batchId);
        // OpenEntityManagerInView may retain the pre-network version across short transactions.
        entityManager.refresh(batch);
        return batch;
    }

    private record VerificationContext(Long accountId, String taskId, String environment,
            List<UnifiedRedemptionRemoteExecutorClient.ConfigurationReference> configurations) { }

    public Long downloadCode(Long issueId) {
        UnifiedRedemptionRemoteExecutorClient executor = unifiedRemoteExecutorClient.getIfAvailable();
        if (executor != null) {
            String attemptedConfigurationId = null;
            Long attemptedPolicyUpdateId = null;
            try {
                // Resolve lazy owner links while the session is open. Only scalar facts may cross remote I/O.
                var preflight = required(tx().execute(status -> {
                    var issue = requireIssue(issueId);
                    RedemptionRewardCheck.requireReady(issue);
                    if ("CODE_IMPORTED".equals(issue.getEffectiveWorkflowStatus())) {
                        RemoteConfigurationIds.requireUsable(issue);
                        clearDownloadError(issue);
                        batchProgress.refresh(requireRemoteBatch(issue));
                        return new DownloadPreflight(issue.getBatchId(), true, null, null, null);
                    }
                    return new DownloadPreflight(issue.getBatchId(), false, publicationBatchId(issue),
                            issue.configurationOwner().getRemoteConfigurationId(),
                            issue.configurationOwner().getPolicyUpdate() == null ? null : issue.configurationOwner().getPolicyUpdate().getId());
                }));
                if (preflight.codeImported()) return preflight.batchId();
                attemptedConfigurationId = preflight.configurationId();
                attemptedPolicyUpdateId = preflight.policyUpdateId();
                Long publicationBatchId = preflight.publicationBatchId();
                var verification = verifyPublication(publicationBatchId);
                if (!"COMPLETED".equals(verification.publicationState())) {
                    throw ApiException.conflict("REMOTE_PUBLICATION_NOT_COMPLETED", "尚未确认远端发布完成，请先核验远端状态");
                }
                if (verification.configurations().stream().noneMatch(item ->
                        Objects.equals(item.configurationId(), preflight.configurationId()) && "MATCHED".equals(item.state()))) {
                    throw ApiException.conflict("REMOTE_CONFIGURATION_MISMATCH", "远端发布已完成，但兑换配置未找到或不匹配，请先核验配置");
                }
                DownloadContext context = required(tx().execute(status -> {
                    var batch = requireFreshBatch(publicationBatchId);
                    if (!verification.remotePublishTaskId().equals(batch.getRemotePublishTaskId())) {
                        throw ApiException.conflict("REMOTE_PUBLISH_STATE_CHANGED", "发布任务已变化，请重新核验");
                    }
                    activateConfirmedPublication(batch);
                    return prepareDownload(issueId);
                }));
                var result = executor.download(context.accountId(), issueId, context.configurationId(), context.groupKey(), context.keyNumber());
                return required(tx().execute(status -> completeDownload(issueId, context.configurationId(), context.policyUpdateId(), result.groupKey(), String.join("\n", result.codes()))));
            } catch (RuntimeException exception) {
                String attemptedId = attemptedConfigurationId;
                Long attemptedPolicyId = attemptedPolicyUpdateId;
                tx().executeWithoutResult(status -> failDownload(issueId, limit(exception.getMessage()), attemptedId, attemptedPolicyId));
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
            return required(tx().execute(status -> completeDownload(issueId, context.configurationId(), context.policyUpdateId(), finalGroupKey, code)));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            tx().executeWithoutResult(status -> failDownload(issueId, error, context.configurationId(), context.policyUpdateId()));
            if (exception instanceof ApiException apiException) throw apiException;
            throw ApiException.badRequest("REMOTE_CODE_DOWNLOAD_FAILED", error);
        }
    }

    private RemoteTaskContext reserveCreate(Long issueId, boolean retryFailed) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        if (RemoteConfigurationIds.needsReconciliation(issue)) throw RemoteConfigurationIds.unconfirmed(issue);
        if (recoveryRepository.countUnresolvedInTask(batch.getTaskId(), null) > 0)
            throw ApiException.conflict("RECOVERY_TASK_STOPPED", "本任务仍有重建结果待核对，已停止后续创建");
        // Enforce the queue stop on the server too, including sibling markets and stale browser tabs.
        var receipts = issueRepository.findCreationReceiptsByTaskId(batch.getTaskId());
        if (receipts.stream().anyMatch(receipt -> RemoteConfigurationIds.isAwaitingReview(receipt.getError()))) {
            throw RemoteConfigurationIds.awaitingReview();
        }
        if (receipts.stream().anyMatch(receipt -> RemoteConfigurationIds.needsReconciliation(
                receipt.getConfigurationId(), receipt.getReferenceId(), receipt.getError())
                || (receipt.getReceiptId() != null && !RemoteConfigurationIds.isValid(receipt.getReceiptId())))) {
            throw RemoteConfigurationIds.unconfirmed();
        }
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
        RemoteCreationOptions options = options(batch);
        RedemptionCodeType type = batch.getRedemptionType();
        // Older multi-code batches still use their saved ordinary-code contract.
        String giftCode = type != null && type.usesSpecialCode() && options.keyNumber() == 1
                ? batch.specialCode(issue.getClaimDate(), issue.getMinDepositAmount()) : null;
        if (giftCode != null && issueRepository.countByBatchIdAndClaimDateAndMinDepositAmount(
                batch.getId(), issue.getClaimDate(), issue.getMinDepositAmount()) > 1) {
            throw ApiException.conflict("DUPLICATE_SPECIAL_CODE", "同批次同日存在相同充值门槛，会生成重复的特殊兑换码");
        }
        // Historical same-code records were reviewed before reservation. They are retained, not erased or rebound.
        issue.setWorkflowStatus("CREATING_REMOTE");
        issue.setState("PENDING");
        issue.setRemoteError(null);
        issue.setRemoteRequestId(UUID.randomUUID().toString());
        issueRepository.saveAndFlush(issue);
        LocalDate validFrom = issue.getClaimDate().plusDays(batch.getValidFromDayOffset() == null ? 0 : batch.getValidFromDayOffset());
        LocalDate validTo = issue.getClaimDate().plusDays(batch.getValidToDayOffset() == null ? 0 : batch.getValidToDayOffset());
        return new RemoteTaskContext(batch.getId(), account, remoteDescription(batch, issue), labels, allUsers,
                issue.getBonusAmount(), issue.getBonusMaxAmount(), issue.getClaimDate(), validFrom, validTo, options, giftCode);
    }

    private Long completeCreate(Long issueId, String configurationId, String groupKey, String warning) {
        RemoteConfigurationIds.requireCreated(configurationId);
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
        issue.setWorkflowStatus(unifiedRemoteExecutorClient.getIfAvailable() == null
                ? "CREATED" : RedemptionRewardCheck.REQUIRED);
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
        auditService.record(RemoteConfigurationIds.isAwaitingReview(error)
                        ? "REDEMPTION_REMOTE_CONFIGURATION_AWAITING_REVIEW" : "REDEMPTION_REMOTE_CONFIGURATION_FAILED",
                "REDEMPTION_CODE_ISSUE", issueId.toString(), null, null,
                Map.of("batchId", batch.getId(), "message", error));
    }

    private Long retryRegistration(Long issueId, boolean retryFailed) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        if (RemoteConfigurationIds.needsReconciliation(issue)) throw RemoteConfigurationIds.unconfirmed(issue);
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
        if (!java.util.Set.of("PENDING_CREATION", "FAILED").contains(issue.getWorkflowStatus())) return;
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
        issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batchId).forEach(RedemptionRewardCheck::requireReady);
        if (request == null || request.rowVersion() == null || !Objects.equals(batch.getRowVersion(), request.rowVersion())) throw ApiException.conflict("BATCH_VERSION_CONFLICT", "批次已被其他人修改，请刷新后重试");
        boolean repair = isRepairing(batch);
        if (!"READY_TO_PUBLISH".equals(batch.getStatus()) && !repair) throw ApiException.conflict("BATCH_NOT_READY_TO_PUBLISH", "请先完成该批次全部远端兑换码配置创建");
        if (repair) {
            var issues = canonicalIssues(batchId);
            if (issues.stream().noneMatch(issue -> "CREATED".equals(issue.getWorkflowStatus()))
                    || issues.stream().anyMatch(issue -> !java.util.Set.of("CREATED", "PUBLISHED", "CODE_IMPORTED").contains(issue.getWorkflowStatus()))) {
                throw ApiException.conflict("REPAIR_NOT_READY_TO_PUBLISH", "缺失配置尚未全部重建，不能重新发布");
            }
            if (Boolean.TRUE.equals(request.fallbackToScheduled())) {
                throw ApiException.badRequest("REPAIR_PUBLISH_MODE_INVALID", "补齐发布不能自动回退定时发布，请明确选择发布方式和时间");
            }
        }
        if (batch.getRemotePublishTaskId() != null && (!repair || batch.getRemotePublishTaskId().startsWith("PENDING:")))
            throw ApiException.conflict("REMOTE_PUBLISH_IN_PROGRESS", "该批次正在执行远端发布，请稍后刷新");
        boolean scheduled = "SCHEDULED".equals(request.mode());
        boolean fallbackToScheduled = request.fallbackToScheduled() == null || request.fallbackToScheduled();
        LocalDateTime scheduledTime = request.scheduledTime();
        if (scheduled && (scheduledTime == null || !scheduledTime.isAfter(nowInIndia()))) {
            throw ApiException.badRequest("INVALID_SCHEDULED_TIME", "定时发布时间必须晚于当前印度时间");
        }
        if (repair && scheduled) {
            LocalDateTime earliestExpiration = canonicalIssues(batchId)
                    .stream().filter(issue -> "CREATED".equals(issue.getWorkflowStatus()))
                    .map(issue -> issue.getClaimDate().plusDays(batch.getValidToDayOffset() == null ? 0 : batch.getValidToDayOffset())
                            .atTime(23, 59, 59))
                    .min(LocalDateTime::compareTo).orElseThrow();
            if (!scheduledTime.isBefore(earliestExpiration)) {
                throw ApiException.badRequest("REPAIR_SCHEDULE_AFTER_EXPIRY", "补齐配置的定时发布时间必须早于最早到期时间（印度时间）");
            }
        }
        RedemptionRemoteDirectory.Account account = remoteDirectory.requireEnabled(batch.getRemoteConnectionId());
        for (RedemptionCodeIssue issue : canonicalIssues(batchId)) {
            requireMatchingMarket(issue, account);
            RemoteConfigurationIds.requireUsable(issue);
        }
        batch.setRemotePublishTaskId("PENDING:" + UUID.randomUUID());
        batch.setRemotePublishError(null);
        batch.setRemotePublishMode(null);
        batch.setRemoteScheduledPublishAt(null);
        batch.setRemotePublishNote(repair ? "缺失配置已重建，正在重新发布；远端将发布该账号全部未发布的兑换码配置" : null);
        batch.setRemotePublishCancelledAt(null);
        batchRepository.saveAndFlush(batch);
        return new RemoteBatchContext(account.id(), null, options(batch), scheduled, scheduledTime,
                scheduled ? repair ? "缺失配置补齐后定时发布（账号下全部未发布兑换码配置）" : "人工定时发布"
                        : repair ? "缺失配置补齐后立即发布（账号下全部未发布兑换码配置）" : "立即发布", batch.getRemotePublishTaskId(), fallbackToScheduled);
    }

    private void requirePublishReservation(Long batchId, RemoteBatchContext context) {
        tx().executeWithoutResult(status -> {
            if (!context.publishTaskId().equals(requireFreshBatch(batchId).getRemotePublishTaskId()))
                throw ApiException.conflict("REMOTE_PUBLISH_STATE_CHANGED", "当前盘口已结束本次系统发布，不再提交发布请求");
        });
    }

    private Long completePublish(Long batchId, String reservation, String publishTaskId, boolean scheduled, LocalDateTime scheduledTime, String note) {
        RedemptionCodeBatch batch = requireFreshBatch(batchId);
        if (!reservation.equals(batch.getRemotePublishTaskId())) {
            auditService.record("REDEMPTION_REMOTE_PUBLISH_LATE_RECEIPT", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                    Map.of("reservation", reservation, "remotePublishTaskId", publishTaskId));
            return batchId;
        }
        List<RedemptionCodeIssue> issues = canonicalIssues(batchId);
        boolean repair = isRepairing(batch);
        if (issues.size() != batch.getExpectedCodeCount() || (repair
                ? issues.stream().noneMatch(issue -> "CREATED".equals(issue.getWorkflowStatus()))
                    || issues.stream().anyMatch(issue -> !java.util.Set.of("CREATED", "PUBLISHED", "CODE_IMPORTED").contains(issue.getWorkflowStatus()))
                : issues.stream().anyMatch(issue -> !java.util.Set.of("CREATED", "PUBLISHED", "CODE_IMPORTED").contains(issue.getWorkflowStatus())))) {
            throw ApiException.conflict("BATCH_NOT_READY_TO_PUBLISH", "该批次仍有未完成的远端配置");
        }
        if (!scheduled) { issues.stream().filter(issue -> "CREATED".equals(issue.getWorkflowStatus())).forEach(issue -> issue.setWorkflowStatus("PUBLISHED")); issueRepository.saveAll(issues); }
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
        issues.forEach(issue -> batchProgress.refreshRelated(issue.getId()));
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
            requirePublishReservation(batchId, context);
            String taskId = remoteClient.publishAll(connection, context.options().publishEnvironment(), true, scheduledTime);
            notes.add("自动回退定时发布第 " + attemptNumber + " 次成功（" + formatIndiaTime(scheduledTime) + "）");
            return required(tx().execute(status -> completePublish(batchId, context.publishTaskId(), taskId, true, scheduledTime, String.join("；", notes))));
        } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
            notes.add("自动回退定时发布第 " + (index + 1) + " 次（" + formatIndiaTime(attempts.get(index)) + "）失败：" + limitNoteError(exception.getMessage()));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            String note = limitNote(String.join("；", notes) + "；自动回退定时发布发生异常，远端状态未知：" + error);
            tx().executeWithoutResult(status -> failPublish(batchId, context.publishTaskId(), "IMMEDIATE", null, note, error));
            if (exception instanceof ApiException apiException) throw apiException;
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        }
        String note = limitNote(String.join("；", notes) + "；自动定时发布均失败");
        tx().executeWithoutResult(status -> failPublish(batchId, context.publishTaskId(), "IMMEDIATE", null, note, limit(note)));
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
            requirePublishReservation(batchId, context);
            UnifiedRedemptionRemoteExecutorClient.PublishedBatch published = executor.publish(
                    context.accountId(), batchId, context.options().publishEnvironment(), true, scheduledTime, false);
            notes.add("自动回退定时发布第 " + attemptNumber + " 次成功（" + formatIndiaTime(scheduledTime) + "）");
            return required(tx().execute(status -> completePublish(
                    batchId, context.publishTaskId(), published.taskId(), true, scheduledTime, String.join("；", notes))));
        } catch (ApiException exception) {
            requirePublishReservation(batchId, context);
            notes.add("自动回退定时发布第 " + (index + 1) + " 次（" + formatIndiaTime(attempts.get(index)) + "）失败："
                    + limitNoteError(exception.getMessage()));
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            String note = limitNote(String.join("；", notes) + "；自动回退定时发布发生异常，远端状态未知：" + error);
            tx().executeWithoutResult(status -> failPublish(batchId, context.publishTaskId(), "IMMEDIATE", null, note, error));
            throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", error);
        }
        String note = limitNote(String.join("；", notes) + "；自动定时发布均失败");
        tx().executeWithoutResult(status -> failPublish(batchId, context.publishTaskId(), "IMMEDIATE", null, note, limit(note)));
        throw ApiException.badRequest("REMOTE_PUBLISH_FAILED", "立即发布及自动定时发布均失败");
    }

    public Long cancelScheduledPublish(Long batchId, Long rowVersion) {
        UnifiedRedemptionRemoteExecutorClient executor = unifiedRemoteExecutorClient.getIfAvailable();
        if (executor == null) remoteOperationGate.requireEnabled("remote_cancel");
        RemoteBatchContext context = required(tx().execute(status -> {
            RedemptionCodeBatch batch = requireBatch(batchId);
            if (rowVersion == null || !Objects.equals(batch.getRowVersion(), rowVersion)) throw ApiException.conflict("BATCH_VERSION_CONFLICT", "批次已被其他人修改，请刷新后重试");
            if (!isCancellableScheduledPublish(batch)) throw ApiException.conflict("SCHEDULED_PUBLISH_NOT_CANCELLABLE", "定时发布时间已到或批次不是定时发布状态");
            if (batch.getRemotePublishTaskId() == null || batch.getRemotePublishTaskId().isBlank()) throw ApiException.conflict("REMOTE_PUBLISH_TASK_REQUIRED", "该定时发布缺少远端任务 ID，不能撤销");
            RedemptionRemoteDirectory.Account account = remoteDirectory.requireEnabled(batch.getRemoteConnectionId());
            for (RedemptionCodeIssue issue : canonicalIssues(batchId)) {
                requireMatchingMarket(issue, account);
            }
            return new RemoteBatchContext(account.id(), executor == null ? requireEnabledConnection(batch) : null,
                    options(batch), true, batch.getRemoteScheduledPublishAt(), "", batch.getRemotePublishTaskId(), false);
        }));
        try {
            if (executor != null) executor.cancelScheduledPublish(context.accountId(), batchId, context.publishTaskId());
            else remoteClient.cancelScheduledPublish(context.connection(), context.publishTaskId());
        } catch (RuntimeException exception) {
            String error = limit(exception.getMessage());
            tx().executeWithoutResult(status -> recordCancelFailure(batchId, error));
            if (exception instanceof ApiException apiException) throw apiException;
            if (executor != null) throw exception;
            throw ApiException.badRequest("REMOTE_SCHEDULED_PUBLISH_CANCEL_FAILED", error);
        }
        return required(tx().execute(status -> completeCancelScheduledPublish(batchId)));
    }

    private Long completeCancelScheduledPublish(Long batchId) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        if (!isCancellableScheduledPublish(batch)) throw ApiException.conflict("SCHEDULED_PUBLISH_NOT_CANCELLABLE", "定时发布状态已变化，请刷新后重试");
        batch.setStatus("READY_TO_PUBLISH");
        batch.setRemotePublishCancelledAt(Instant.now());
        batch.setRemotePublishNote(appendNote(batch.getRemotePublishNote(), "已人工撤销定时发布，不再进行后续自动定时发布尝试"));
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
            batch.setRemotePublishNote(appendNote(batch.getRemotePublishNote(), "撤销定时发布失败：" + error + "；原定发布时间：" + formatIndiaTime(batch.getRemoteScheduledPublishAt())));
            batchRepository.save(batch);
        }
        auditService.record("REDEMPTION_REMOTE_SCHEDULED_PUBLISH_CANCEL_FAILED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("message", error));
    }

    private void failPublish(Long batchId, String reservation, String mode, LocalDateTime scheduledTime, String note, String error) {
        RedemptionCodeBatch batch = requireFreshBatch(batchId);
        if (!reservation.equals(batch.getRemotePublishTaskId())) return;
        batch.setRemotePublishTaskId(null);
        batch.setRemotePublishMode(mode);
        batch.setRemoteScheduledPublishAt(scheduledTime);
        batch.setRemotePublishNote(limitNote(note));
        batch.setRemotePublishError(limit(error));
        batchRepository.save(batch);
        auditService.record("REDEMPTION_REMOTE_BATCH_PUBLISH_FAILED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("message", error));
    }

    private DownloadContext prepareDownload(Long issueId) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        issue = issue.configurationOwner();
        if (unifiedRemoteExecutorClient.getIfAvailable() == null) activateStandaloneScheduledPublishIfDue(batch);
        if (!("PUBLISHED".equals(issue.getWorkflowStatus()) || "CODE_IMPORTED".equals(issue.getWorkflowStatus()))) {
            throw ApiException.conflict("REMOTE_DOWNLOAD_NOT_ALLOWED", "请先发布该远端兑换码配置");
        }
        RemoteConfigurationIds.requireUsable(issue);
        Long downloadAccountId = issue.getCurrentRecovery() != null && "COMPLETED".equals(issue.getCurrentRecovery().getStatus())
                ? issue.getCurrentRecovery().getAccountId() : batch.getRemoteConnectionId();
        requireMatchingMarket(issue, remoteDirectory.requireEnabled(downloadAccountId));
        return new DownloadContext(batch.getId(), unifiedRemoteExecutorClient.getIfAvailable() == null ? requireEnabledConnection(batch) : null,
                issue.getRemoteConfigurationId(), issue.getRemoteGroupKey(), remoteDescription(batch, issue),
                downloadAccountId, effectiveKeyNumber(issue, batch), issue.getPolicyUpdate() == null ? null : issue.getPolicyUpdate().getId());
    }

    /**
     * The remote publish API has no completion callback. Once its configured India-time schedule has passed, the
     * first download request advances the locally tracked issues to PUBLISHED. Any remote export error remains on
     * the affected issue, rather than claiming that the scheduled task completed successfully.
     */
    private void activateStandaloneScheduledPublishIfDue(RedemptionCodeBatch batch) {
        if (!("PUBLISHED".equals(batch.getStatus()) && "SCHEDULED".equals(batch.getRemotePublishMode())
                && batch.getRemoteScheduledPublishAt() != null && !batch.getRemoteScheduledPublishAt().isAfter(nowInIndia()))) {
            return;
        }
        List<RedemptionCodeIssue> issues = canonicalIssues(batch.getId());
        List<RedemptionCodeIssue> createdIssues = issues.stream().filter(issue -> "CREATED".equals(issue.getWorkflowStatus())).toList();
        if (createdIssues.isEmpty()) return;
        createdIssues.forEach(issue -> issue.setWorkflowStatus("PUBLISHED"));
        issueRepository.saveAll(createdIssues);
        batch.setRemotePublishNote(appendNote(batch.getRemotePublishNote(), "已到定时发布时间，开始下载兑换码"));
        batchRepository.save(batch);
    }

    private void activateConfirmedPublication(RedemptionCodeBatch batch) {
        var issues = canonicalIssues(batch.getId());
        var created = issues.stream().filter(issue -> "CREATED".equals(issue.getWorkflowStatus())).toList();
        if (created.isEmpty()) return;
        created.forEach(issue -> issue.setWorkflowStatus("PUBLISHED"));
        issueRepository.saveAll(created);
        created.forEach(issue -> batchProgress.refreshRelated(issue.getId()));
        batch.setRemotePublishNote(appendNote(batch.getRemotePublishNote(), "已核验远端发布完成，开始下载兑换码"));
        batchRepository.save(batch);
    }

    private Long completeDownload(Long issueId, String expectedConfigurationId, Long expectedPolicyUpdateId, String groupKey, String code) {
        RedemptionCodeIssue requested = requireIssue(issueId);
        RedemptionCodeIssue issue = requested.configurationOwner();
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        if (!Objects.equals(expectedConfigurationId, issue.getRemoteConfigurationId())
                || !Objects.equals(expectedPolicyUpdateId, issue.getPolicyUpdate() == null ? null : issue.getPolicyUpdate().getId()))
            throw ApiException.conflict("REMOTE_CONFIGURATION_CHANGED", "下载期间配置身份已变化；旧配置回包未计入新配置，请刷新后重试下载");
        RemoteConfigurationIds.requireUsable(issue);
        codeStorage.storeDownloaded(issue, batch, code == null ? List.of() : code.lines().toList());
        issue.setRemoteGroupKey(groupKey);
        issue.setWorkflowStatus("CODE_IMPORTED");
        issue.setState("GENERATED");
        issue.setRemoteError(null);
        issue.setGeneratedAt(Instant.now());
        issue.setInventoryConfigurationId(issue.getRemoteConfigurationId());
        issueRepository.save(issue);
        clearDownloadError(requested);
        batchProgress.refreshRelated(issue.getId());
        auditService.record("REDEMPTION_REMOTE_CODE_DOWNLOADED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null, null,
                Map.of("batchId", requested.getBatchId(), "ownerIssueId", issue.getId(), "remoteConfigurationId", issue.getRemoteConfigurationId()));
        return requested.getBatchId();
    }

    private void clearDownloadError(RedemptionCodeIssue issue) {
        if (issue.getRemoteError() != null) {
            issue.setRemoteError(null);
            issueRepository.save(issue);
        }
    }

    private void failDownload(Long issueId, String error, String expectedConfigurationId, Long expectedPolicyUpdateId) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireRemoteBatch(issue);
        if ((expectedConfigurationId == null || Objects.equals(expectedConfigurationId, issue.configurationOwner().getRemoteConfigurationId()))
                && Objects.equals(expectedPolicyUpdateId, issue.configurationOwner().getPolicyUpdate() == null ? null : issue.configurationOwner().getPolicyUpdate().getId())
                && !"CODE_IMPORTED".equals(issue.getEffectiveWorkflowStatus())) {
            issue.setRemoteError(error);
            issueRepository.save(issue);
        }
        auditService.record("REDEMPTION_REMOTE_CODE_DOWNLOAD_FAILED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null, null,
                Map.of("batchId", batch.getId(), "message", error));
    }

    private void refreshBatchAfterCreation(RedemptionCodeBatch batch) {
        if (isRepairing(batch)) return;
        batchProgress.refresh(batch);
    }
    private void refreshBatchAfterImport(RedemptionCodeBatch batch) {
        batchProgress.refresh(batch);
    }
    private boolean isRepairing(RedemptionCodeBatch batch) {
        return "CREATING".equals(batch.getStatus()) && batch.getPublishedAt() != null;
    }
    private List<RedemptionCodeIssue> canonicalIssues(Long batchId) {
        return issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batchId).stream()
                .map(RedemptionCodeIssue::configurationOwner).distinct().toList();
    }

    private Long publicationBatchId(RedemptionCodeIssue issue) {
        var owner = issue.configurationOwner();
        var candidates = new java.util.LinkedHashSet<Long>();
        candidates.add(issue.getBatchId());
        candidates.addAll(issueRepository.findRelatedBatchIds(owner.getId()));
        for (Long id : candidates) {
            var batch = requireBatch(id);
            String taskId = batch.getRemotePublishTaskId();
            if (taskId != null && !taskId.isBlank() && !taskId.startsWith("PENDING:")
                    && !isRepairing(batch) && batch.getRemotePublishCancelledAt() == null) return id;
        }
        throw ApiException.conflict("REMOTE_PUBLICATION_NOT_COMPLETED", "该共享配置尚无可核验的发布任务，请先完成发布");
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
    static int effectiveKeyNumber(RedemptionCodeIssue issue, RedemptionCodeBatch batch) {
        var r = issue.configurationOwner().getCurrentRecovery();
        return r != null && "COMPLETED".equals(r.getStatus()) ? r.getKeyNumber()
                : batch.getRemoteKeyNumber() == null ? 1 : batch.getRemoteKeyNumber();
    }

    static RemoteCreationOptions options(RedemptionCodeBatch batch) {
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
        return RedemptionRemoteDescription.forIssue(batch, issue, labelIds(issue));
    }
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
                                     RemoteCreationOptions options, String giftCode) { }
    private record RemoteBatchContext(Long accountId, RedemptionRemoteConnection connection, RemoteCreationOptions options, boolean scheduled,
                                      LocalDateTime scheduledTime, String note, String publishTaskId,
                                      boolean fallbackToScheduled) { }
    private record DownloadPreflight(Long batchId, boolean codeImported, Long publicationBatchId, String configurationId, Long policyUpdateId) { }
    private record DownloadContext(Long batchId, RedemptionRemoteConnection connection, String configurationId, String groupKey,
                                   String description, Long accountId, int keyNumber, Long policyUpdateId) { }
}
