package com.rajads.erp.redemption;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.audit.AuditService;
import com.rajads.erp.shared.ApiException;
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;

/** Read-verify-link. No remote create, update, publish or code import is performed here. */
@Service
@RequiredArgsConstructor
public class RedemptionReuseService {
    @org.springframework.beans.factory.annotation.Value("${erp.redemption.reuse-enabled:true}")
    private boolean newAssociationsEnabled;
    private static final ReentrantLock[] LOCKS = java.util.stream.IntStream.range(0, 256)
            .mapToObj(i -> new ReentrantLock()).toArray(ReentrantLock[]::new);
    private final RedemptionCodeIssueRepository issues;
    private final RedemptionCodeBatchRepository batches;
    private final RedemptionRemoteDirectory directory;
    private final ObjectProvider<UnifiedRedemptionRemoteExecutorClient> executor;
    private final PlatformTransactionManager transactionManager;
    private final EntityManager entityManager;
    private final ObjectMapper mapper;
    private final AuditService audit;
    private final RedemptionBatchProgress progress;
    private final RedemptionRecoveryService recovery;
    private final RedemptionPolicyUpdateService policyUpdates;

    public <T> T withIssueLock(Long issueId, Supplier<T> work) {
        int key = tx().execute(s -> {
            var issue = issue(issueId);
            var batch = batch(issue.getBatchId());
            return Objects.hash(issue.getRemoteMarketId(), code(batch, issue));
        });
        var lock = LOCKS[Math.floorMod(key, LOCKS.length)];
        lock.lock();
        try { return work.get(); } finally { lock.unlock(); }
    }

    public Long reuse(Long issueId, Long rowVersion) { return reuse(issueId,rowVersion,null); }

    public Long reuse(Long issueId, Long rowVersion, String configurationId) {
        if(configurationId!=null && !RemoteConfigurationIds.isValid(configurationId))
            throw ApiException.badRequest("INVALID_REMOTE_CONFIGURATION_ID","请选择有效的远端配置 ID");
        return withIssueLock(issueId, () -> {
            Long batchId = tryReuse(issueId, rowVersion, configurationId);
            if (batchId == null) throw ApiException.conflict("REUSE_CONFIGURATION_NOT_FOUND",
                    "未找到可核验复用的本地配置；原任务保持不变，不会重新提交远端创建。");
            return batchId;
        });
    }

    public Long tryReuse(Long issueId, Long expectedVersion) { return tryReuse(issueId,expectedVersion,null); }

    private Long tryReuse(Long issueId, Long expectedVersion, String selectedConfigurationId) {
        var context = tx().execute(s -> prepare(issueId, expectedVersion, selectedConfigurationId));
        if (context == null) return null;
        if (context.existingLink()) {
            policyUpdates.verifyForCreation(issueId);
            return context.batchId();
        }
        var recoveryState = tx().execute(s -> RedemptionRecoveryService.summary(issue(issueId)));
        if (recoveryState != null && !Set.of("PRESENT", "COMPLETED").contains(recoveryState.status()))
            throw ApiException.conflict("REMOTE_CONFIGURATION_RECOVERY_REQUIRED", recoveryState.reason());
        var ownerRecovery = tx().execute(s -> RedemptionRecoveryService.summary(issue(context.ownerId())));
        if (ownerRecovery != null && !Set.of("PRESENT", "COMPLETED").contains(ownerRecovery.status())) {
            var result = recovery.inspect(issueId, context.ownerId(), context.issueVersion());
            throw ApiException.conflict("REMOTE_CONFIGURATION_RECOVERY_REQUIRED", result.reason());
        }
        if (!newAssociationsEnabled) throw ApiException.conflict("REUSE_DISABLED", "新增复用关联暂时关闭，已有配置和关联保留。");
        var client = executor.getIfAvailable();
        if (client == null) throw ApiException.conflict("REUSE_CHECK_UNAVAILABLE", "复用需要统一远端账号核验服务");
        UnifiedRedemptionRemoteExecutorClient.ReuseCheck check;
        try { check = client.checkReuse(context.accountId(), issueId, context.configurationId(), context.description(),
                context.claimDate(), context.validFrom(), context.validTo(), context.labels(), context.bonusMin(),
                context.bonusMax(), context.options(), context.code());
        } catch (RuntimeException failure) {
            var result = recovery.inspect(issueId, context.ownerId(), context.issueVersion());
            if ("MISSING".equals(result.status())) throw ApiException.conflict("REMOTE_CONFIGURATION_MISSING",
                    "旧配置确认缺失，进度已保存。请点击重试并重建，按本次任务参数重新创建。");
            throw ApiException.conflict("RECOVERY_CHECK_UNAVAILABLE", result.reason());
        }
        if (check == null) throw ApiException.conflict("REUSE_CHECK_UNAVAILABLE", "远端复用核验未返回结果");
        // Identity may be shared; a new task's reward decision remains independent.
        if (selectedConfigurationId!=null && check.differences().stream().anyMatch(d -> !Set.of("reward_min","reward_max").contains(d)))
            throw ApiException.conflict("REUSE_SELECTED_CONFIGURATION_MISMATCH","所选配置还有本次任务参数不一致，未关联；请先调整并回读核验。 ");
        if (check.differences().contains("gift_code")) throw ApiException.conflict(
                "REUSE_CONFIGURATION_IDENTITY_MISMATCH", "远端配置的码串与本任务不同，不能关联。");
        return tx().execute(s -> link(issueId, context, check));
    }

    /** Used only by an explicitly requested create, never by the read-and-link action. */
    public void verifyCodeAbsent(Long issueId) {
        if (!newAssociationsEnabled) throw ApiException.conflict("REUSE_DISABLED", "新增复用及核验后重试暂时关闭。");
        var context = tx().execute(s -> absenceContext(issueId));
        var client = executor.getIfAvailable();
        if (client == null) throw ApiException.conflict("REUSE_CHECK_UNAVAILABLE", "缺少统一远端核验服务，不能重试。");
        var proof = client.checkAbsence(context.accountId(), issueId, context.code());
        if (proof == null || !context.code().equalsIgnoreCase(proof.giftCode()))
            throw ApiException.conflict("REUSE_UNCONFIRMED_CONFIGURATION", "未获得完整远端不存在性证据，不能重新创建。");
        tx().executeWithoutResult(s -> {
            var current = absenceContext(issueId);
            if (!context.equals(current)) throw ApiException.conflict("REUSE_STATE_CHANGED", "核验期间任务发生变化，请刷新后重试。");
            audit.record("REDEMPTION_CODE_ABSENCE_CONFIRMED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null,
                    null, Map.of("giftCode", context.code(), "scannedRows", proof.scannedRows(),
                            "scannedPages", proof.scannedPages(), "checkedAt", proof.checkedAt(),
                            "originalTasksUnchanged", true));
        });
    }

    private AbsenceContext absenceContext(Long issueId) {
        // Re-evaluate the existing owner/identity checks before and after remote I/O.
        try {
            prepare(issueId, null, null);
        } catch (ApiException exception) {
            if (!"REUSE_UNCONFIRMED_CONFIGURATION".equals(exception.getCode())) throw exception;
            var target = issue(issueId);
            var group = batch(target.getBatchId());
            if (target.getRemoteConfigurationId() != null || target.getRemoteCreateReceiptId() != null
                    || target.getRemoteReferenceId() != null || target.getReusedFromIssue() != null
                    || !Set.of("PENDING_CREATION", "FAILED").contains(target.getWorkflowStatus()))
                throw ApiException.conflict("REUSE_UNCONFIRMED_CONFIGURATION", "当前任务自身有未确认结果，不能重新创建。");
            return new AbsenceContext(group.getId(), group.getRemoteConnectionId(), target.getRowVersion(),
                    group.getRowVersion(), code(group, target));
        }
        throw ApiException.conflict("REUSE_STATE_CHANGED", "同码任务状态已变化，请刷新后重新核验。");
    }

    private record AbsenceContext(Long batchId, Long accountId, Long issueVersion, Long batchVersion, String code) { }

    private Context prepare(Long issueId, Long expectedVersion, String selectedConfigurationId) {
        var issue = issue(issueId);
        entityManager.refresh(issue);
        if (expectedVersion != null && !Objects.equals(issue.getRowVersion(), expectedVersion))
            throw ApiException.conflict("ISSUE_VERSION_CONFLICT", "任务已变化，请刷新后重试");
        var batch = batch(issue.getBatchId());
        if (batch.getRemoteConnectionId() == null) return null;
        if (issue.getReusedFromIssue() != null) return Context.linked(batch.getId());
        if (RemoteConfigurationIds.isValid(issue.getRemoteConfigurationId())) return null;
        if (!Set.of("PENDING_CREATION", "FAILED", "CREATING_REMOTE", "CREATED").contains(issue.getWorkflowStatus()))
            throw ApiException.conflict("REUSE_STATE_NOT_ALLOWED", "该任务已有发布或入库事实，不能重新关联配置");
        if (!issue.getCodes().isEmpty() || issues.existsByReusedFromIssueId(issueId))
            throw ApiException.conflict("REUSE_OWNERSHIP_LOCKED", "该任务已有库存或被其他任务引用，不能重关联");
        if ("CREATING_REMOTE".equals(issue.getWorkflowStatus())
                && issue.getUpdatedAt().isAfter(Instant.now().minus(Duration.ofMinutes(2))))
            throw ApiException.conflict("REMOTE_CREATE_STILL_RUNNING", "创建请求仍可能在执行，请稍后核验");
        String code = code(batch, issue);
        if (code == null) return null;
        var account = directory.requireEnabled(batch.getRemoteConnectionId());
        if (!Objects.equals(account.marketId(), issue.getRemoteMarketId()) || issue.getRemoteMarketId() <= 0)
            throw ApiException.conflict("REMOTE_MARKET_CHANGED", "远端账号盘口与任务不一致");
        var candidates = issues.findReuseCandidates(issue.getRemoteMarketId(), issueId,
                code.toLowerCase(Locale.ROOT), batch.getRedemptionType(), issue.getClaimDate().getMonthValue(),
                issue.getClaimDate().getDayOfMonth(), issue.getMinDepositAmount(), batch.getSpecialCodeNaming());
        var owners = candidates.stream().filter(i -> RemoteConfigurationIds.isValid(i.getRemoteConfigurationId())
                && !RemoteConfigurationIds.needsReconciliation(i)
                && (Set.of("CREATED", "PUBLISHED", "CODE_IMPORTED").contains(i.getWorkflowStatus())
                    || RedemptionRewardCheck.pending(i))).toList();
        if(selectedConfigurationId!=null) {
            owners=owners.stream().filter(i -> selectedConfigurationId.equals(i.getRemoteConfigurationId())).toList();
            if(owners.isEmpty()) throw ApiException.conflict("REUSE_SELECTION_CHANGED","所选配置不属于当前盘口和同码候选，请重新核对。");
        }
        if (owners.isEmpty()) {
            if (candidates.stream().anyMatch(RemoteConfigurationIds::needsReconciliation))
                throw ApiException.conflict("REUSE_UNCONFIRMED_CONFIGURATION", "同码的其他任务仍有未确认创建结果，请先核对，不能重复提交。");
            return null;
        }
        if (owners.size() != 1) throw ApiException.conflict("REUSE_AMBIGUOUS_CONFIGURATION", "同码找到多个历史配置，请明确选择已核验的远端配置 ID。",
            Map.of("candidates",owners.stream().map(i -> Map.of("configurationId",i.getRemoteConfigurationId(),"ownerIssueId",i.getId(),"batchId",i.getBatchId())).toList()));
        var owner = owners.get(0);
        RedemptionDeletionService.requireAvailable(owner);
        if (RemoteConfigurationIds.isValid(issue.getRemoteCreateReceiptId())
                && !Objects.equals(issue.getRemoteCreateReceiptId(), owner.getRemoteConfigurationId()))
            throw ApiException.conflict("REUSE_RECEIPT_CONFLICT", "已有创建回执与同码配置 ID 不一致，请先核对，不能自动关联。");
        if (!owner.getCodes().isEmpty() && (owner.getCodes().size() != 1
                || !owner.getCodes().getFirst().equalsIgnoreCase(code)))
            throw ApiException.conflict("REUSE_INVENTORY_MISMATCH", "原任务保存的码与待复用码不一致，请先核对库存。");
        if (issues.countByBatchIdAndClaimDateAndMinDepositAmount(batch.getId(), issue.getClaimDate(), issue.getMinDepositAmount()) > 1
                || issues.countOwnerReferencesInTask(batch.getTaskId(), owner.getId()) > 0)
            throw ApiException.conflict("DUPLICATE_SPECIAL_CODE", "同一个任务不能重复包含同一份兑换配置，请使用已有任务行。");
        List<Long> labels;
        try { labels = issue.getRemoteLabelIdsJson() == null ? List.of() : mapper.readValue(issue.getRemoteLabelIdsJson(), new TypeReference<>() {}); }
        catch (Exception e) { throw ApiException.conflict("REUSE_INVALID_LABELS", "任务标签快照无效，不能复用"); }
        return new Context(batch.getId(), account.id(), issue.getRowVersion(), owner.getId(), owner.getRowVersion(),
                owner.getRemoteConfigurationId(), code, RedemptionRemoteDescription.forIssue(batch, issue, labels),
                issue.getClaimDate(), issue.getClaimDate().plusDays(Objects.requireNonNullElse(batch.getValidFromDayOffset(), 0)),
                issue.getClaimDate().plusDays(Objects.requireNonNullElse(batch.getValidToDayOffset(), 0)), labels,
                issue.getBonusAmount(), issue.getBonusMaxAmount(), RedemptionRemoteOperationService.options(batch), false, batch.getRowVersion());
    }

    private Long link(Long issueId, Context context, UnifiedRedemptionRemoteExecutorClient.ReuseCheck check) {
        // Refresh both rows after I/O and take locks in a stable order before changing the relationship.
        for (Long id : java.util.stream.Stream.of(issueId, context.ownerId()).sorted().toList()) {
            entityManager.refresh(issue(id), LockModeType.PESSIMISTIC_WRITE);
        }
        var target = issue(issueId);
        var owner = issue(context.ownerId());
        var batch = batch(target.getBatchId());
        entityManager.refresh(batch);
        if (!Objects.equals(target.getRowVersion(), context.issueVersion())
                || !Objects.equals(owner.getRowVersion(), context.ownerVersion())
                || !Objects.equals(owner.getRemoteConfigurationId(), context.configurationId())
                || owner.getReusedFromIssue() != null || issues.existsByReusedFromIssueId(issueId)
                || !Objects.equals(batch.getRowVersion(), context.batchVersion())
                || !Objects.equals(batch.getRemoteConnectionId(), context.accountId())
                || !Objects.equals(target.getRemoteMarketId(), owner.getRemoteMarketId()))
            throw ApiException.conflict("REUSE_STATE_CHANGED", "核验期间任务或配置已变化，请刷新后重试");
        RedemptionDeletionService.requireAvailable(owner);
        RemoteConfigurationIds.requireUsable(owner);
        var before = new LinkedHashMap<String, Object>();
        before.put("workflowStatus", target.getWorkflowStatus());
        before.put("remoteConfigurationId", target.getRemoteConfigurationId());
        before.put("remoteReferenceId", target.getRemoteReferenceId());
        before.put("remoteCreateReceiptId", target.getRemoteCreateReceiptId());
        before.put("remoteGroupKey", target.getRemoteGroupKey());
        before.put("remoteError", target.getRemoteError());
        target.setPendingRecovery(null);
        target.setReusedFromIssue(owner);
        target.setRemoteConfigurationId(null);
        target.setRemoteReferenceId(null);
        target.setRemoteCreateReceiptId(null);
        target.setRemoteGroupKey(null);
        // Missing actual values must also remain visibly pending, even when the old owner is fully imported.
        String rewardState = "CREATED";
        String rewardReason = null;
        try {
            if (!RedemptionRewardCheck.matches(check, context.configurationId(), context.bonusMin(), context.bonusMax())) {
                rewardState = RedemptionRewardCheck.CONFIRM;
                rewardReason = RedemptionRewardCheck.difference(check, context.bonusMin(), context.bonusMax());
            }
        } catch (ApiException unavailable) {
            rewardState = RedemptionRewardCheck.REQUIRED;
            rewardReason = unavailable.getMessage();
        }
        target.setRemoteError(rewardReason);
        target.setWorkflowStatus(rewardState);
        target.setState("PENDING");
        issues.saveAndFlush(target);
        progress.refresh(batch);
        audit.record("REDEMPTION_CONFIGURATION_REUSED", "REDEMPTION_CODE_ISSUE", issueId.toString(), null,
                before, Map.of("ownerIssueId", owner.getId(), "ownerBatchId", owner.getBatchId(),
                        "configurationId", context.configurationId(), "requestedSingleKeyLimit", context.options().singleKeyLimit(),
                        "parameterDifferences", check.differences(), "rewardStatus", rewardState,
                        "effectivePolicy", "EXISTING_REMOTE_CONFIGURATION"));
        return batch.getId();
    }

    private String code(RedemptionCodeBatch batch, RedemptionCodeIssue issue) {
        return batch.getRedemptionType() != null && batch.getRedemptionType().usesSpecialCode()
                && Objects.equals(batch.getRemoteKeyNumber(), 1)
                ? batch.specialCode(issue.getClaimDate(), issue.getMinDepositAmount()) : null;
    }
    private RedemptionCodeIssue issue(Long id) { return issues.findById(id).orElseThrow(() -> ApiException.notFound("兑换码任务")); }
    private RedemptionCodeBatch batch(Long id) {
        if (id == null) throw ApiException.conflict("NOT_BATCH_TASK", "该任务不属于兑换码批次");
        return batches.findById(id).orElseThrow(() -> ApiException.notFound("兑换码批次"));
    }
    private TransactionTemplate tx() { return new TransactionTemplate(transactionManager); }
    private record Context(Long batchId, Long accountId, Long issueVersion, Long ownerId, Long ownerVersion,
            String configurationId, String code, String description, java.time.LocalDate claimDate,
            java.time.LocalDate validFrom, java.time.LocalDate validTo, List<Long> labels,
            java.math.BigDecimal bonusMin, java.math.BigDecimal bonusMax, RemoteCreationOptions options, boolean existingLink, Long batchVersion) {
        static Context linked(Long batchId) { return new Context(batchId, null, null, null, null, null, null, null,
                null, null, null, null, null, null, null, true, null); }
    }
}
