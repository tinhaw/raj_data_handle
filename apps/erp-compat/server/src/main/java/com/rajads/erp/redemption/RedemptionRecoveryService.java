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

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.*;

/** Explicit read / confirm / create / receipt / readback / register generation recovery.
 * Every network call is outside the database transaction. A reserved or uncertain write is never replayed.
 */
@Service
@RequiredArgsConstructor
public class RedemptionRecoveryService {
    private static final Set<String> IN_FLIGHT = Set.of("CREATING", "UNCONFIRMED", "RECEIPT_SAVED", "APPLYING");
    @org.springframework.beans.factory.annotation.Value("${erp.redemption.recovery-enabled:true}")
    private boolean rebuildEnabled;
    private final RedemptionCodeIssueRepository issues;
    private final RedemptionCodeBatchRepository batches;
    private final RedemptionRecoveryRepository recoveries;
    private final RedemptionRemoteDirectory directory;
    private final ObjectProvider<UnifiedRedemptionRemoteExecutorClient> executors;
    private final PlatformTransactionManager transactionManager;
    private final EntityManager em;
    private final ObjectMapper mapper;
    private final RedemptionBatchProgress progress;
    private final AuditService audit;

    public record Snapshot(Long issueId, Long issueVersion, Long ownerId, Long ownerVersion,
            Long batchId, Long batchVersion, Long accountId, Long marketId, String marketName,
            String description, LocalDate claimDate, LocalDate validFrom, LocalDate validTo,
            List<Long> labels, BigDecimal bonusMin, BigDecimal bonusMax, RemoteCreationOptions options, String code, List<Long> linkedIssueIds, List<BatchVersion> sharedBatches) { }
    public record BatchVersion(Long id, Long rowVersion) { }
    public record View(Long id, String status, String reason, Long rowVersion, Long requestedIssueId,
            Long ownerIssueId, String oldConfigurationId, String newConfigurationId,
            Instant checkedAt, int relatedBatchCount, Snapshot parameters) { }
    public record Summary(Long id, String status, String reason, Long rowVersion, Long requestedIssueId,
            String oldConfigurationId, String newConfigurationId) { }
    public record InspectRequest(Long rowVersion) { }
    public record RebuildRequest(Long recoveryId, Long rowVersion, boolean confirmed) { }
    private record Probe(Snapshot snapshot, String configurationId, String groupKey, boolean inventory) { }

    public static Summary summary(RedemptionCodeIssue issue) {
        var r = issue.getReusedFromIssue() == null && issue.getPendingRecovery() != null ? issue.getPendingRecovery() : issue.configurationOwner().getActiveRecovery();
        return r == null ? null : new Summary(r.getId(), r.getStatus(), r.getReason(), r.getRowVersion(),
                r.getRequestedIssueId(), r.getOldConfigurationId(), r.getNewConfigurationId());
    }

    /** Secret-free parameter snapshot also used by the separately authorized reward-only editor. */
    public Snapshot policySnapshot(Long issueId) {
        return tx().execute(s -> { var target = issue(issueId); em.refresh(target); var owner = target.configurationOwner(); RedemptionDeletionService.requireAvailable(owner);
            if (!owner.getId().equals(target.getId())) em.refresh(owner);
            if (!RemoteConfigurationIds.isValid(owner.getRemoteConfigurationId())) throw changed();
            return snapshot(target, owner); });
    }

    /** Only the explicit KEEP flow may inspect a held identity; it does not authorize a remote write. */
    Snapshot deletionHoldSnapshot(Long issueId) {
        return tx().execute(s -> { var target=issue(issueId);em.refresh(target);var owner=target.configurationOwner();em.refresh(owner);
            if (!RemoteConfigurationIds.isValid(owner.getRemoteConfigurationId())) throw changed();
            return snapshot(target,owner); });
    }

    public View inspect(Long issueId, Long expectedVersion) { return inspect(issueId, null, expectedVersion); }

    // Called only after reuse has selected one unambiguous canonical identity. Still performs a fresh independent probe.
    public View inspect(Long issueId, Long candidateOwnerId, Long expectedVersion) {
        Probe probe = tx().execute(s -> probe(issueId, candidateOwnerId, expectedVersion));
        var current = tx().execute(s -> active(probe.snapshot().ownerId()));
        if (current != null && IN_FLIGHT.contains(current.status())) {
            tx().executeWithoutResult(s -> {
                var target = issue(issueId);
                if (target.getReusedFromIssue() == null && !Objects.equals(target.getId(), current.ownerIssueId())) {
                    target.setPendingRecovery(recovery(current.id())); issues.saveAndFlush(target);
                    progress.refresh(batch(target.getBatchId()));
                }
            });
            return current;
        }
        UnifiedRedemptionRemoteExecutorClient.RecoveryCheck check;
        try {
            check = executor().checkRecovery(probe.snapshot(), probe.configurationId(), probe.groupKey(), probe.inventory());
            if (check == null) throw ApiException.conflict("RECOVERY_CHECK_UNAVAILABLE", "未取得有效缺失核验结果");
        } catch (RuntimeException failure) {
            return tx().execute(s -> saveProbe(probe, "CHECK_UNAVAILABLE", "核验不可用；未重新创建。请恢复读取后重试核验。", null));
        }
        String status = "ABSENT".equals(check.state()) ? "MISSING" : "PRESENT";
        String reason = "MISSING".equals(status)
                ? "旧配置及同码已在授权目录内确认缺失；进度已保存，请点击重试并重建。"
                : "远端仍有配置或同码，不能重建；请核对已有配置关联。";
        return tx().execute(s -> saveProbe(probe, status, reason, check));
    }

    public Long rebuild(Long issueId, RebuildRequest request) {
        if (!rebuildEnabled) throw ApiException.conflict("RECOVERY_DISABLED", "重建创建暂时关闭；已有回执、身份和历史库存保留。");
        if (request == null || !request.confirmed() || request.recoveryId() == null || request.rowVersion() == null)
            throw ApiException.badRequest("RECOVERY_CONFIRMATION_REQUIRED", "请核对本次任务参数并明确确认重新创建");
        View view = tx().execute(s -> requireView(issueId, request));
        if ("COMPLETED".equals(view.status())) return view.parameters().batchId();
        if ("RECEIPT_SAVED".equals(view.status())) return finish(request.recoveryId());
        if (!"MISSING".equals(view.status())) throw blocked(view.status());
        // Even a fresh browser preview is insufficient: independently re-prove absence before reserving a write.
        Probe probe = tx().execute(s -> probe(issueId, view.ownerIssueId(), null));
        if (!view.parameters().equals(probe.snapshot())) throw changed();
        UnifiedRedemptionRemoteExecutorClient.RecoveryCheck check;
        try { check = executor().checkRecovery(probe.snapshot(), probe.configurationId(), probe.groupKey(), probe.inventory()); }
        catch (RuntimeException failure) {
            tx().executeWithoutResult(s -> saveProbe(probe, "CHECK_UNAVAILABLE", "重试核验不可用；未重新创建。请重新核验。", null));
            throw ApiException.conflict("RECOVERY_CHECK_UNAVAILABLE", "重试核验不可用，未重新创建");
        }
        if (check == null || !"ABSENT".equals(check.state()) || check.checkedAt().isBefore(Instant.now().minusSeconds(60))) {
            tx().executeWithoutResult(s -> saveProbe(probe, "CHECK_UNAVAILABLE", "旧配置或同码状态已变化；未重新创建，请重新核验。", null));
            throw ApiException.conflict("RECOVERY_NOT_ABSENT", "未确认旧配置及同码缺失，未重新创建");
        }
        Snapshot snapshot = tx().execute(s -> reserve(issueId, request, check));
        UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration created;
        try {
            created = executor().create(snapshot.accountId(), snapshot.issueId(), snapshot.description(),
                    snapshot.claimDate(), snapshot.validFrom(), snapshot.validTo(), snapshot.labels(),
                    snapshot.bonusMin(), snapshot.bonusMax(), snapshot.options(), snapshot.code());
            RemoteConfigurationIds.requireCreated(created.configurationId());
            if (!created.configurationId().matches("[1-9][0-9]*") || created.configurationId().equals(view.oldConfigurationId())) throw changed();
        } catch (RuntimeException failure) {
            tx().executeWithoutResult(s -> markUnconfirmed(request.recoveryId()));
            throw ApiException.conflict("RECOVERY_CREATE_UNCONFIRMED",
                    "创建结果待核对，已停止重试；请核对远端回执，不能重复提交。");
        }
        // Committed separately: registration/readback failures only resume this receipt, never the create call.
        tx().executeWithoutResult(s -> {
            var r = lockedRecovery(request.recoveryId());
            if (!Set.of("CREATING", "UNCONFIRMED").contains(r.getStatus()) || r.getNewConfigurationId() != null) throw changed();
            r.setNewConfigurationId(created.configurationId()); r.setNewGroupKey(created.groupKey());
            r.setStatus("RECEIPT_SAVED"); r.setReason("远端已创建，登记待恢复；重试仅核验并登记，不再次创建。");
            recoveries.saveAndFlush(r);
            audit.record("REDEMPTION_RECOVERY_RECEIPT_SAVED", "REDEMPTION_RECOVERY", r.getId().toString(), null,
                    null, Map.of("newConfigurationId", r.getNewConfigurationId(), "ownerIssueId", r.getOwnerIssueId()));
        });
        return finish(request.recoveryId());
    }

    private Long finish(Long recoveryId) {
        var view = tx().execute(s -> view(recovery(recoveryId)));
        if ("COMPLETED".equals(view.status())) return view.parameters().batchId();
        if (!"RECEIPT_SAVED".equals(view.status())) throw blocked(view.status());
        var snapshot = view.parameters();
        var result = executor().checkReuse(snapshot.accountId(), snapshot.issueId(), view.newConfigurationId(),
                snapshot.description(), snapshot.claimDate(), snapshot.validFrom(), snapshot.validTo(), snapshot.labels(),
                snapshot.bonusMin(), snapshot.bonusMax(), snapshot.options(), snapshot.code());
        if (result == null || !Objects.equals(result.configurationId(), view.newConfigurationId())
                || !result.matched() || !result.differences().isEmpty())
            throw ApiException.conflict("RECOVERY_READBACK_MISMATCH", "远端已创建但回读参数尚未匹配；保留回执，重试仅恢复登记。");
        if (result.groupKey() != null) tx().executeWithoutResult(s -> {
            var r = lockedRecovery(recoveryId);
            if (!"RECEIPT_SAVED".equals(r.getStatus())) return;
            if (r.getNewGroupKey() != null && !r.getNewGroupKey().equals(result.groupKey()))
                throw ApiException.conflict("RECOVERY_GROUP_MISMATCH", "远端回读兑换组与创建回执不符，保留回执等待核对");
            r.setNewGroupKey(result.groupKey()); recoveries.saveAndFlush(r);
        });
        return tx().execute(s -> apply(recoveryId));
    }

    private Snapshot reserve(Long issueId, RebuildRequest request, UnifiedRedemptionRemoteExecutorClient.RecoveryCheck check) {
        var r = recovery(request.recoveryId());
        lockIssues(issueId, r.getOwnerIssueId());
        r = lockedRecovery(request.recoveryId());
        if (!Objects.equals(r.getRowVersion(), request.rowVersion()) || !"MISSING".equals(r.getStatus())
                || !Objects.equals(r.getRequestedIssueId(), issueId)) throw changed();
        var snapshot = read(r.getSnapshotJson(), Snapshot.class);
        if (!snapshot.equals(snapshot(issue(issueId), issue(r.getOwnerIssueId())))) throw changed();
        checkTaskStop(snapshot.batchId(), r.getId());
        r.setStatus("CREATING"); r.setCheckedAt(check.checkedAt());
        r.setProofRows(check.scannedRows()); r.setProofPages(check.scannedPages());
        r.setReason("重建中；重复提交已锁定，请等待回执。");
        recoveries.saveAndFlush(r);
        audit.record("REDEMPTION_RECOVERY_RESERVED", "REDEMPTION_RECOVERY", r.getId().toString(), null,
                null, Map.of("ownerIssueId", r.getOwnerIssueId(), "requestedIssueId", issueId));
        return snapshot;
    }

    private Long apply(Long recoveryId) {
        var r = recovery(recoveryId);
        lockIssues(r.getRequestedIssueId(), r.getOwnerIssueId());
        r = lockedRecovery(recoveryId);
        var snapshot = read(r.getSnapshotJson(), Snapshot.class);
        if ("COMPLETED".equals(r.getStatus())) return snapshot.batchId();
        if (!"RECEIPT_SAVED".equals(r.getStatus())) throw changed();
        var owner = issue(r.getOwnerIssueId()); var target = issue(r.getRequestedIssueId());
        if (!snapshot.equals(snapshot(target, owner)) || !Objects.equals(owner.getRemoteConfigurationId(), r.getOldConfigurationId())) throw changed();
        var duplicate = issues.findByRemoteMarketIdAndRemoteConfigurationId(r.getRemoteMarketId(), r.getNewConfigurationId());
        if (duplicate.isPresent() && !duplicate.get().getId().equals(owner.getId()))
            throw ApiException.conflict("REMOTE_CONFIGURATION_ID_EXISTS", "新配置 ID 已被其他任务登记；保留回执等待核对");
        // Retain a typed, generation-specific inventory archive before replacing any current inventory.
        int index = 0;
        for (String code : owner.getCodes()) {
            var history = new RedemptionHistoricalCode(); history.setRecoveryId(r.getId());
            history.setOwnerIssueId(owner.getId()); history.setRemoteMarketId(owner.getRemoteMarketId());
            history.setCodeIndex(index++); history.setCode(code);
            history.setConfigurationId(owner.getInventoryConfigurationId() == null ? r.getOldConfigurationId() : owner.getInventoryConfigurationId()); em.persist(history);
        }
        r.setStatus("APPLYING"); recoveries.saveAndFlush(r);
        // PostgreSQL's identity guard accepts this one journal-backed transition only in this transaction.
        em.unwrap(org.hibernate.Session.class).doWork(connection -> {
            if (connection.getMetaData().getDatabaseProductName().equals("PostgreSQL")) {
                try (var statement = connection.prepareStatement("select set_config('erp.redemption_recovery', ?, true)")) {
                    statement.setString(1, recoveryId.toString()); statement.execute();
                }
            }
        });
        if (owner.getInventoryConfigurationId() == null && !owner.getCodes().isEmpty()) owner.setInventoryConfigurationId(r.getOldConfigurationId());
        owner.setPolicyUpdate(null);
        owner.setCurrentRecovery(r);
        owner.setRemoteConfigurationId(r.getNewConfigurationId()); owner.setRemoteReferenceId(r.getNewConfigurationId());
        owner.setRemoteCreateReceiptId(r.getNewConfigurationId()); owner.setRemoteGroupKey(r.getNewGroupKey());
        owner.setWorkflowStatus("CREATED"); owner.setState("PENDING"); owner.setRemoteError(null);
        // Historical inventory stays in place until a verified new generation import replaces the current projection.
        issues.saveAndFlush(owner);
        if (!target.getId().equals(owner.getId()) && target.getReusedFromIssue() == null) {
            if (!target.getCodes().isEmpty() || RemoteConfigurationIds.isValid(target.getRemoteConfigurationId())) throw changed();
            target.setReusedFromIssue(owner); target.setRemoteConfigurationId(null); target.setRemoteReferenceId(null);
            target.setRemoteCreateReceiptId(null); target.setRemoteGroupKey(null);
            target.setWorkflowStatus("CREATED"); target.setState("PENDING");
        }
        target.setPendingRecovery(null); target.setRemoteError(null); issues.saveAndFlush(target);
        r.setStatus("COMPLETED"); r.setReason("配置已按任务快照创建：奖励 " + snapshot.bonusMin().stripTrailingZeros().toPlainString()
                + "–" + snapshot.bonusMax().stripTrailingZeros().toPlainString() + "，每码 " + snapshot.options().singleKeyLimit()
                + " 次，每组 " + snapshot.options().keyNumber() + " 码；待单独确认发布。");
        // Every referencing batch loses its old generation's publication proof, which remains in history_json.
        for (Long batchId : issues.findRelatedBatchIds(owner.getId())) {
            var batch = batch(batchId); em.refresh(batch, LockModeType.PESSIMISTIC_WRITE);
            batch.setRemotePublishTaskId(null); batch.setPublishedAt(null); batch.setRemotePublishMode(null);
            batch.setRemoteScheduledPublishAt(null); batch.setRemotePublishCancelledAt(null);
            batch.setRemotePublishNote("缺失配置已重建，旧发布证明已归档；请单独确认发布。");
            progress.refresh(batch);
        }
        recoveries.saveAndFlush(r);
        audit.record("REDEMPTION_RECOVERY_COMPLETED", "REDEMPTION_RECOVERY", recoveryId.toString(), null,
                Map.of("configurationId", r.getOldConfigurationId()), Map.of("configurationId", r.getNewConfigurationId(),
                        "ownerIssueId", owner.getId(), "requestedIssueId", target.getId()));
        return target.getBatchId();
    }

    private Probe probe(Long issueId, Long candidateOwnerId, Long expectedVersion) {
        var target = issue(issueId); em.refresh(target);
        if (expectedVersion != null && !expectedVersion.equals(target.getRowVersion())) throw changed();
        RedemptionCodeIssue owner = candidateOwnerId == null ? target.configurationOwner() : issue(candidateOwnerId);
        if (!RemoteConfigurationIds.isValid(owner.getRemoteConfigurationId()) && owner.getId().equals(target.getId())) {
            var b = batch(target.getBatchId()); var code = specialCode(b, target);
            if (code == null) throw ApiException.conflict("RECOVERY_IDENTITY_REQUIRED", "没有可核验的原配置身份");
            var candidates = issues.findReuseCandidates(target.getRemoteMarketId(), target.getId(), code.toLowerCase(Locale.ROOT),
                    b.getRedemptionType(), target.getClaimDate().getMonthValue(), target.getClaimDate().getDayOfMonth(), target.getMinDepositAmount(), b.getSpecialCodeNaming())
                    .stream().filter(i -> RemoteConfigurationIds.isValid(i.getRemoteConfigurationId())).toList();
            if (candidates.size() != 1) throw ApiException.conflict("RECOVERY_IDENTITY_REQUIRED", "没有唯一的原配置所有者，请先核对关联");
            owner = candidates.getFirst();
        }
        if (owner.getReusedFromIssue() != null || !RemoteConfigurationIds.isValid(owner.getRemoteConfigurationId())
                || !Objects.equals(target.getRemoteMarketId(), owner.getRemoteMarketId())
                || RemoteConfigurationIds.needsReconciliation(target) || RemoteConfigurationIds.needsReconciliation(owner)) throw changed();
        if (!Set.of("CREATED", "PUBLISHED", "CODE_IMPORTED").contains(owner.getWorkflowStatus())
                || "CREATING_REMOTE".equals(target.getWorkflowStatus()))
            throw ApiException.conflict("RECOVERY_CREATE_IN_FLIGHT", "原配置或本任务仍有未核对的创建请求，不能重新创建");
        if (!target.getId().equals(owner.getId()) && target.getReusedFromIssue() == null) {
            if (target.getRemoteCreateReceiptId() != null
                    && !Objects.equals(target.getRemoteCreateReceiptId(), owner.getRemoteConfigurationId())) throw changed();
            var targetCode = specialCode(batch(target.getBatchId()), target);
            var ownerCode = owner.getCodes().size() == 1 ? owner.getCodes().getFirst() : specialCode(batch(owner.getBatchId()), owner);
            if (targetCode == null || !targetCode.equalsIgnoreCase(Objects.toString(ownerCode, ""))
                    || !target.getCodes().isEmpty() || RemoteConfigurationIds.isValid(target.getRemoteConfigurationId())
                    || issues.existsByReusedFromIssueId(target.getId())) throw changed();
        }
        RedemptionDeletionService.requireAvailable(owner);
        return new Probe(snapshot(target, owner), owner.getRemoteConfigurationId(), owner.getRemoteGroupKey(), !owner.getCodes().isEmpty());
    }

    private View saveProbe(Probe probe, String status, String reason, UnifiedRedemptionRemoteExecutorClient.RecoveryCheck check) {
        var s = probe.snapshot(); lockIssues(s.issueId(), s.ownerId());
        var target = issue(s.issueId()); var owner = issue(s.ownerId());
        if (!s.equals(snapshot(target, owner)) || !Objects.equals(owner.getRemoteConfigurationId(), probe.configurationId())) throw changed();
        var r = recoveries.findByOwnerIssueIdAndOldConfigurationId(owner.getId(), probe.configurationId()).orElseGet(RedemptionRecovery::new);
        if (r.getStatus() != null && IN_FLIGHT.contains(r.getStatus())) return view(r);
        r.setOwnerIssueId(owner.getId()); r.setRequestedIssueId(target.getId()); r.setRemoteMarketId(owner.getRemoteMarketId());
        r.setKeyNumber(s.options().keyNumber()); r.setAccountId(s.accountId());
        r.setOldConfigurationId(probe.configurationId()); r.setStatus(status); r.setReason(reason); r.setCheckedAt(check == null ? null : check.checkedAt());
        r.setProofRows(check == null ? 0 : check.scannedRows()); r.setProofPages(check == null ? 0 : check.scannedPages());
        r.setSnapshotJson(json(s));
        if (r.getHistoryJson() == null) {
            var related = new ArrayList<Map<String, Object>>();
            for (Long batchId : issues.findRelatedBatchIds(owner.getId())) {
                var b = batch(batchId); var facts = new LinkedHashMap<String, Object>();
                facts.put("batchId", batchId); facts.put("publishTaskId", b.getRemotePublishTaskId());
                facts.put("publishedAt", b.getPublishedAt()); facts.put("publishMode", b.getRemotePublishMode());
                facts.put("scheduledAt", b.getRemoteScheduledPublishAt()); facts.put("cancelledAt", b.getRemotePublishCancelledAt());
                facts.put("publishNote", b.getRemotePublishNote()); facts.put("rowVersion", b.getRowVersion()); related.add(facts);
            }
            var history = new LinkedHashMap<String, Object>(); history.put("owner", snapshot(owner, owner));
            history.put("previousPolicyUpdateId", owner.getPolicyUpdate() == null ? null : owner.getPolicyUpdate().getId());
            history.put("previousGenerationId", owner.getCurrentRecovery() == null ? null : owner.getCurrentRecovery().getId());
            history.put("codes", owner.getCodes()); history.put("groupKey", owner.getRemoteGroupKey());
            history.put("workflowStatus", owner.getWorkflowStatus()); history.put("generatedAt", owner.getGeneratedAt());
            history.put("relatedBatches", related); r.setHistoryJson(json(history));
        }
        recoveries.saveAndFlush(r); owner.setActiveRecovery(r);
        if (!target.getId().equals(owner.getId()) && target.getReusedFromIssue() == null) target.setPendingRecovery(r);
        issues.saveAndFlush(owner); issues.saveAndFlush(target);
        progress.refreshRelated(owner.getId());
        if (target.getReusedFromIssue() == null && !target.getId().equals(owner.getId())) progress.refresh(batch(target.getBatchId()));
        batches.flush();
        // Pointer writes change versions. Store exactly the snapshot that the next confirmation must still match.
        r.setSnapshotJson(json(snapshot(target, owner))); recoveries.saveAndFlush(r);
        audit.record("REDEMPTION_RECOVERY_CHECKED", "REDEMPTION_RECOVERY", r.getId().toString(), null,
                null, Map.of("state", status, "ownerIssueId", owner.getId(), "requestedIssueId", target.getId()));
        return view(r);
    }

    private Snapshot snapshot(RedemptionCodeIssue target, RedemptionCodeIssue owner) {
        var b = batch(target.getBatchId()); em.refresh(b);
        var account = directory.requireEnabled(b.getRemoteConnectionId());
        if (!Objects.equals(account.marketId(), target.getRemoteMarketId()) || !Objects.equals(account.marketId(), owner.getRemoteMarketId())) throw changed();
        List<Long> labels = read(target.getRemoteLabelIdsJson() == null ? "[]" : target.getRemoteLabelIdsJson(), new TypeReference<List<Long>>() {});
        var shared = new ArrayList<BatchVersion>();
        for (Long id : issues.findRelatedBatchIds(owner.getId()).stream().filter(Objects::nonNull).sorted().toList()) {
            var related = batch(id); em.refresh(related);
            if (related.getRemotePublishTaskId() != null && related.getRemotePublishTaskId().startsWith("PENDING:")
                    || related.getRemotePublishCancelledAt() == null && related.getRemoteScheduledPublishAt() != null
                    && related.getRemoteScheduledPublishAt().isAfter(java.time.LocalDateTime.now(java.time.ZoneId.of("Asia/Kolkata"))))
                throw ApiException.conflict("RECOVERY_PUBLICATION_ACTIVE", "共享批次仍有发布请求或未撤销的定时发布，请先核对或撤销后再重建");
            shared.add(new BatchVersion(id, related.getRowVersion()));
        }
        return new Snapshot(target.getId(), target.getRowVersion(), owner.getId(), owner.getRowVersion(), b.getId(), b.getRowVersion(),
                account.id(), account.marketId(), account.marketName(), RedemptionRemoteDescription.forIssue(b, target, labels),
                target.getClaimDate(), target.getClaimDate().plusDays(Objects.requireNonNullElse(b.getValidFromDayOffset(),0)),
                target.getClaimDate().plusDays(Objects.requireNonNullElse(b.getValidToDayOffset(),0)), labels,
                target.getBonusAmount(), target.getBonusMaxAmount(), RedemptionRemoteOperationService.options(b), specialCode(b, target), issues.findRelatedIssueIds(owner.getId()), shared);
    }

    private void checkTaskStop(Long batchId, Long exceptId) {
        if (recoveries.countUnresolvedInTask(batch(batchId).getTaskId(), exceptId) > 0)
            throw ApiException.conflict("RECOVERY_TASK_STOPPED", "本任务仍有重建请求执行中或结果待核对，已停止后续创建");
        var receipts = issues.findCreationReceiptsByTaskId(batch(batchId).getTaskId());
        if (receipts.stream().anyMatch(r -> RemoteConfigurationIds.isAwaitingReview(r.getError()))) throw RemoteConfigurationIds.awaitingReview();
        if (receipts.stream().anyMatch(r -> RemoteConfigurationIds.needsReconciliation(r.getConfigurationId(), r.getReferenceId(), r.getError())
                || r.getReceiptId() != null && !RemoteConfigurationIds.isValid(r.getReceiptId()))) throw RemoteConfigurationIds.unconfirmed();
    }
    private void markUnconfirmed(Long id) { var r = lockedRecovery(id); r.setStatus("UNCONFIRMED");
        r.setReason("创建结果待核对；远端可能已接收请求，禁止自动再次创建。"); recoveries.saveAndFlush(r); }
    private View requireView(Long issueId, RebuildRequest request) {
        var r = recovery(request.recoveryId());
        if (!Objects.equals(r.getRequestedIssueId(), issueId)) throw changed();
        if (!"COMPLETED".equals(r.getStatus()) && !Objects.equals(r.getRowVersion(), request.rowVersion())) throw changed();
        return view(r);
    }
    private View active(Long ownerId) {
        var r = issue(ownerId).getActiveRecovery();
        if (r == null) return null;
        if ("CREATING".equals(r.getStatus()) && r.getUpdatedAt().isBefore(Instant.now().minusSeconds(120))) {
            r = lockedRecovery(r.getId());
            if ("CREATING".equals(r.getStatus()) && r.getUpdatedAt().isBefore(Instant.now().minusSeconds(120))) {
                r.setStatus("UNCONFIRMED"); r.setReason("创建请求已超过等待期，结果待核对；禁止重复提交，请先核对远端回执。");
                recoveries.saveAndFlush(r);
            }
        }
        return view(r);
    }
    private View view(RedemptionRecovery r) { return new View(r.getId(), r.getStatus(), r.getReason(), r.getRowVersion(),
            r.getRequestedIssueId(), r.getOwnerIssueId(), r.getOldConfigurationId(), r.getNewConfigurationId(), r.getCheckedAt(),
            issues.findRelatedBatchIds(r.getOwnerIssueId()).size(), read(r.getSnapshotJson(), Snapshot.class)); }
    private String specialCode(RedemptionCodeBatch b, RedemptionCodeIssue i) { return b.getRedemptionType() != null
            && b.getRedemptionType().usesSpecialCode() && Objects.equals(b.getRemoteKeyNumber(),1)
            ? b.specialCode(i.getClaimDate(), i.getMinDepositAmount()) : null; }
    private void lockIssues(Long first, Long second) { for (Long id : java.util.stream.Stream.of(first, second).distinct().sorted().toList())
        em.refresh(issue(id), LockModeType.PESSIMISTIC_WRITE); }
    private RedemptionRecovery lockedRecovery(Long id) { var r = recovery(id); em.refresh(r, LockModeType.PESSIMISTIC_WRITE); return r; }
    private RedemptionRecovery recovery(Long id) { return recoveries.findById(id).orElseThrow(() -> ApiException.notFound("配置恢复记录")); }
    private RedemptionCodeIssue issue(Long id) { return issues.findById(id).orElseThrow(() -> ApiException.notFound("兑换码任务")); }
    private RedemptionCodeBatch batch(Long id) { return batches.findById(id).orElseThrow(() -> ApiException.notFound("兑换码批次")); }
    private UnifiedRedemptionRemoteExecutorClient executor() { var c = executors.getIfAvailable(); if (c == null)
        throw ApiException.conflict("RECOVERY_CHECK_UNAVAILABLE", "重建需要统一远端执行服务"); return c; }
    private TransactionTemplate tx() { return new TransactionTemplate(transactionManager); }
    private ApiException changed() { return ApiException.conflict("RECOVERY_STATE_CHANGED", "任务、参数或恢复记录已变化，请重新核验并确认"); }
    private ApiException blocked(String status) { return ApiException.conflict("RECOVERY_NOT_RETRYABLE", "当前恢复状态 " + status + " 不允许重新创建，请核对回执或重新核验"); }
    private String json(Object value) { try { return mapper.writeValueAsString(value); } catch (Exception e) { throw changed(); } }
    private <T> T read(String value, Class<T> type) { try { return mapper.readValue(value, type); } catch (Exception e) { throw changed(); } }
    private <T> T read(String value, TypeReference<T> type) { try { return mapper.readValue(value, type); } catch (Exception e) { throw changed(); } }
}
