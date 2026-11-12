package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
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
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;

/** Reward-only update. Missing identities go through recovery; they are never created here. */
@Service @RequiredArgsConstructor
public class RedemptionPolicyUpdateService {
    static final String HOLD = RemoteConfigurationIds.UNCONFIRMED_PREFIX + "：奖励修改结果待核对";
    private final RedemptionCodeIssueRepository issues;
    private final RedemptionCodeBatchRepository batches;
    private final RedemptionPolicyUpdateRepository updates;
    private final RedemptionRecoveryService recovery;
    private final RedemptionBatchProgress progress;
    private final ObjectProvider<UnifiedRedemptionRemoteExecutorClient> executors;
    private final EntityManager em;
    private final PlatformTransactionManager tm;
    private final ObjectMapper mapper;
    private final AuditService audit;

    public record View(Long id,String status,String reason,Long rowVersion,Long requestedIssueId,
            Long ownerIssueId,String configurationId,BigDecimal previousMin,BigDecimal previousMax,
            RedemptionRecoveryService.Snapshot parameters) { }
    public record ApplyRequest(Long policyUpdateId,Long rowVersion,boolean confirmed) { }
    private record Context(RedemptionRecoveryService.Snapshot snapshot,String configurationId) { }

    /** The create/reuse entry point always finishes with an actual reward read, never an inherited inventory fact. */
    public void verifyForCreation(Long issueId) {
        tx().executeWithoutResult(s -> {
            var target = issue(issueId);
            if (!RedemptionRewardCheck.pending(target)) {
                // A completed owner must not lose its inventory state on an idempotent create call.
                if (target.getReusedFromIssue() == null && "CODE_IMPORTED".equals(target.getWorkflowStatus()))
                    throw ApiException.conflict("ALREADY_IMPORTED", "配置已入库，请使用核验实际奖励入口");
                target.setWorkflowStatus(RedemptionRewardCheck.REQUIRED);
                target.setState("PENDING");
                target.setRemoteError("配置身份已登记，正在核验实际奖励；核验一致后才可继续。");
                issues.saveAndFlush(target);
                progress.refresh(batch(target.getBatchId()));
            }
        });
        try { check(issueId, null); }
        catch (RuntimeException failure) {
            tx().executeWithoutResult(s -> {
                var target = issue(issueId);
                if (RedemptionRewardCheck.pending(target)) {
                    target.setRemoteError("实际奖励核验未完成，请点击核验奖励后继续；已有配置不会重复创建。");
                    issues.saveAndFlush(target); progress.refresh(batch(target.getBatchId()));
                }
            });
            throw failure;
        }
    }

    public View check(Long issueId,Long expectedVersion) {
        var context=tx().execute(s->context(issueId,expectedVersion));
        var result=read(context);
        boolean rewardsMatch=RedemptionRewardCheck.matches(result, context.configurationId(),
                context.snapshot().bonusMin(), context.snapshot().bonusMax());
        if (!rewardsMatch) requireRewardsOnly(result);
        var active=tx().execute(s->{var r=issue(context.snapshot().ownerId()).getPolicyUpdate();
            if(r==null) return (View)null;
            if("UPDATING".equals(r.getStatus()) && r.getUpdatedAt().isBefore(Instant.now().minusSeconds(120))) {
                r=lockedUpdate(r.getId());
                if("UPDATING".equals(r.getStatus()) && r.getUpdatedAt().isBefore(Instant.now().minusSeconds(120))) {
                    r.setStatus("UNCONFIRMED");r.setReason("奖励修改请求已超过等待期；只读核对结果，禁止重复提交。");updates.saveAndFlush(r);
                }
            }
            return view(r);});
        if (active!=null && !Set.of("CHECKED","APPLIED").contains(active.status())) {
            if (!Objects.equals(active.requestedIssueId(),issueId))
                throw ApiException.conflict("POLICY_SHARED_UPDATE_PENDING", "共享配置有其他任务的奖励修改待核对，请先处理原请求；当前任务不会代替确认。");
            return active;
        }
        if (rewardsMatch) {
            var verified=tx().execute(s->recordCreationCheck(context,result,true));
            return new View(null,"MATCHED","远端实际奖励已符合本任务快照。",null,issueId,
                    verified.snapshot().ownerId(),verified.configurationId(),result.actualMin(),result.actualMax(),verified.snapshot());
        }
        var pending=tx().execute(s->recordCreationCheck(context,result,false));
        return tx().execute(s->prepare(pending,result));
    }

    private Context recordCreationCheck(Context expected, UnifiedRedemptionRemoteExecutorClient.ReuseCheck result, boolean matched) {
        var s=expected.snapshot(); lock(s.issueId(),s.ownerId());
        var current=context(s.issueId(),null);
        if (!s.equals(current.snapshot()) || !expected.configurationId().equals(current.configurationId())) throw changed();
        var target=issue(s.issueId());
        if (RedemptionRewardCheck.pending(target)) {
            target.setWorkflowStatus(matched ? "CREATED" : RedemptionRewardCheck.CONFIRM);
            target.setRemoteError(matched ? null : RedemptionRewardCheck.difference(result,s.bonusMin(),s.bonusMax()));
            issues.saveAndFlush(target); progress.refresh(batch(target.getBatchId())); batches.flush();
            audit.record("REDEMPTION_CREATION_REWARD_CHECKED","REDEMPTION_CODE_ISSUE",target.getId().toString(),null,null,
                    Map.of("configurationId",expected.configurationId(),"matched",matched,
                            "actualMin",result.actualMin(),"actualMax",result.actualMax(),
                            "requestedMin",s.bonusMin(),"requestedMax",s.bonusMax()));
        }
        return context(s.issueId(),null);
    }

    public Long apply(Long issueId,ApplyRequest request) {
        if(request==null || !request.confirmed() || request.policyUpdateId()==null || request.rowVersion()==null)
            throw ApiException.badRequest("POLICY_CONFIRMATION_REQUIRED","必须确认本次已有配置奖励修改");
        var view=tx().execute(s->{var r=update(request.policyUpdateId());
            if(!Objects.equals(r.getRequestedIssueId(),issueId)) throw changed();
            if(!"APPLIED".equals(r.getStatus()) && !Objects.equals(r.getRowVersion(),request.rowVersion())) throw changed();
            return view(r);});
        if("APPLIED".equals(view.status())) return view.parameters().batchId();
        if("UPDATED".equals(view.status())) return finish(request.policyUpdateId());
        if("UPDATING".equals(view.status()) && tx().execute(s->update(request.policyUpdateId()).getUpdatedAt()).isAfter(Instant.now().minusSeconds(120)))
            throw ApiException.conflict("POLICY_STILL_RUNNING","奖励修改请求仍在执行，请等待回执");
        var context=new Context(view.parameters(),view.configurationId());
        var checked=read(context); requireRewardsOnly(checked);
        if(RedemptionRewardCheck.matches(checked,view.configurationId(),view.parameters().bonusMin(),view.parameters().bonusMax())) {
            tx().executeWithoutResult(s->markUpdated(request.policyUpdateId()));
            return finish(request.policyUpdateId());
        }
        if(!"CHECKED".equals(view.status())) throw ApiException.conflict("POLICY_RESULT_UNCONFIRMED",
                "上次奖励修改结果尚未确认；保留配置身份，禁止重复提交，请先核对远端结果。");
        if (checked.actualMin().compareTo(view.previousMin()) != 0 || checked.actualMax().compareTo(view.previousMax()) != 0)
            throw ApiException.conflict("POLICY_STATE_CHANGED", "远端实际奖励已变化，请重新核验并确认修改范围");
        executor().requireRewardUpdateCapability(view.parameters().accountId(), issueId);
        var reserved=tx().execute(s->reserve(request.policyUpdateId(),request.rowVersion()));
        try {
            var result=executor().updateReward(reserved.snapshot(),reserved.configurationId());
            if(result==null || !result.matched() || !Objects.equals(result.configurationId(),reserved.configurationId()))
                throw changed();
        } catch(RuntimeException failure) {
            tx().executeWithoutResult(s->{var r=lockedUpdate(request.policyUpdateId());
                r.setStatus("UNCONFIRMED"); r.setReason("奖励修改结果待核对；重试只读核对，禁止再次提交修改。"); updates.saveAndFlush(r);});
            throw ApiException.conflict("POLICY_RESULT_UNCONFIRMED","奖励修改结果待核对；已保存进度，不会自动重新提交。");
        }
        tx().executeWithoutResult(s->markUpdated(request.policyUpdateId()));
        return finish(request.policyUpdateId());
    }

    private View prepare(Context context,UnifiedRedemptionRemoteExecutorClient.ReuseCheck checked) {
        var s=context.snapshot(); lock(s.issueId(),s.ownerId());
        var current=context(s.issueId(),null); if(!s.equals(current.snapshot())) throw changed();
        var owner=issue(s.ownerId()); var active=owner.getPolicyUpdate();
        if(active!=null && !"APPLIED".equals(active.getStatus())) {
            if(!Objects.equals(active.getRequestedIssueId(),s.issueId()) || !intent(snapshot(active)).equals(intent(s))) throw changed();
            if(!"CHECKED".equals(active.getStatus())) return view(active);
        }
        String key=hash(context.configurationId()+":"+intent(s)+":"+checked.actualMin().stripTrailingZeros().toPlainString()
                +":"+checked.actualMax().stripTrailingZeros().toPlainString()+":"+(active==null?"initial":active.getId()));
        var r=active!=null && "CHECKED".equals(active.getStatus()) ? active
                : updates.findByOwnerIssueIdAndPlanKey(s.ownerId(),key).orElseGet(RedemptionPolicyUpdate::new);
        if(r.getId()==null) {
            r.setOwnerIssueId(s.ownerId()); r.setRequestedIssueId(s.issueId()); r.setRemoteMarketId(s.marketId());
            r.setConfigurationId(context.configurationId()); r.setPlanKey(key); r.setStatus("CHECKED");
            var previous=new LinkedHashMap<String,Object>(); previous.put("bonusMin",checked.actualMin()); previous.put("bonusMax",checked.actualMax());
            var shared=new ArrayList<Map<String,Object>>();
            for(Long id:issues.findRelatedBatchIds(s.ownerId())) {
                var b=batch(id); var fact=new LinkedHashMap<String,Object>();fact.put("batchId",id);fact.put("publishTaskId",b.getRemotePublishTaskId());
                fact.put("publishedAt",b.getPublishedAt());fact.put("publishMode",b.getRemotePublishMode());fact.put("scheduledAt",b.getRemoteScheduledPublishAt());shared.add(fact);
            }
            previous.put("sharedBatches",shared);r.setHistoryJson(json(previous));
        }
        r.setSnapshotJson(json(s));r.setReason("实际奖励与任务不同；确认后仅修改奖励，保留原码、配置 ID、描述与库存。");
        updates.saveAndFlush(r);return view(r);
    }

    private Context reserve(Long id,Long expectedVersion) {
        var r=update(id);lock(r.getRequestedIssueId(),r.getOwnerIssueId());r=lockedUpdate(id);
        if(!"CHECKED".equals(r.getStatus()) || !Objects.equals(r.getRowVersion(),expectedVersion)) throw changed();
        var s=snapshot(r);var current=context(s.issueId(),null);if(!s.equals(current.snapshot())) throw changed();
        var owner=issue(s.ownerId());var target=issue(s.issueId());
        var active=owner.getPolicyUpdate();
        if(active!=null && !active.getId().equals(id) && !"APPLIED".equals(active.getStatus())) throw changed();
        owner.setPolicyUpdate(r);owner.setRemoteError(HOLD);target.setRemoteError(HOLD);
        issues.saveAndFlush(owner);issues.saveAndFlush(target);progress.refreshRelated(owner.getId());batches.flush();
        r.setSnapshotJson(json(recovery.policySnapshot(target.getId())));r.setStatus("UPDATING");r.setReason("正在修改奖励；禁止重复提交。");updates.saveAndFlush(r);
        audit.record("REDEMPTION_REWARD_UPDATE_RESERVED","REDEMPTION_POLICY_UPDATE",id.toString(),null,null,
                Map.of("ownerIssueId",owner.getId(),"requestedIssueId",target.getId(),"configurationId",r.getConfigurationId()));
        return new Context(snapshot(r),r.getConfigurationId());
    }

    private void markUpdated(Long id) {
        var r=lockedUpdate(id);
        if("APPLIED".equals(r.getStatus())) return;
        if(!Set.of("CHECKED","UPDATING","UNCONFIRMED","UPDATED").contains(r.getStatus())) throw changed();
        r.setStatus("UPDATED");r.setReason("远端奖励已回读匹配，待恢复本地登记；不会再次修改。");updates.saveAndFlush(r);
    }

    private Long finish(Long id) {
        var context=tx().execute(s->{var r=update(id);return new Context(snapshot(r),r.getConfigurationId());});
        var checked=read(context);requireRewardsOnly(checked);
        if(!RedemptionRewardCheck.matches(checked,context.configurationId(),context.snapshot().bonusMin(),context.snapshot().bonusMax()))
            throw ApiException.conflict("POLICY_READBACK_MISMATCH","远端奖励未匹配，请核对；不恢复旧发布证明");
        return tx().execute(s->{var r=update(id);lock(r.getRequestedIssueId(),r.getOwnerIssueId());r=lockedUpdate(id);
            if("APPLIED".equals(r.getStatus())) return snapshot(r).batchId();
            if(!"UPDATED".equals(r.getStatus())) throw changed();
            var saved=snapshot(r);var current=context(saved.issueId(),null);
            if(!saved.equals(current.snapshot()) || !r.getConfigurationId().equals(current.configurationId())) throw changed();
            var owner=issue(r.getOwnerIssueId());var target=issue(r.getRequestedIssueId());
            owner.setPolicyUpdate(r);owner.setRemoteError(null);target.setRemoteError(null);
            owner.setWorkflowStatus("CREATED");owner.setState("PENDING");
            if (RedemptionRewardCheck.pending(target)) target.setWorkflowStatus("CREATED");
            issues.saveAndFlush(owner);issues.saveAndFlush(target);
            r.setStatus("APPLIED");r.setReason("奖励已按本次任务快照调整；原配置与库存保留，待单独确认发布。");updates.saveAndFlush(r);
            for(Long batchId:issues.findRelatedBatchIds(owner.getId())) {
                var b=batch(batchId);em.refresh(b,LockModeType.PESSIMISTIC_WRITE);
                b.setRemotePublishTaskId(null);b.setPublishedAt(null);b.setRemotePublishMode(null);b.setRemoteScheduledPublishAt(null);b.setRemotePublishCancelledAt(null);
                b.setRemotePublishNote("已有配置奖励已按任务快照调整；旧发布证明已归档，请单独确认发布。");progress.refresh(b);
            }
            audit.record("REDEMPTION_REWARD_UPDATE_APPLIED","REDEMPTION_POLICY_UPDATE",id.toString(),null,
                    readJson(r.getHistoryJson()),Map.of("configurationId",r.getConfigurationId(),"bonusMin",saved.bonusMin(),"bonusMax",saved.bonusMax()));
            return target.getBatchId();});
    }

    private Context context(Long issueId,Long version) {
        var target=issue(issueId);em.refresh(target);var owner=target.configurationOwner(); RedemptionDeletionService.requireAvailable(owner);if(!owner.getId().equals(target.getId())) em.refresh(owner);
        if(version!=null && !version.equals(target.getRowVersion())) throw changed();
        if(!RemoteConfigurationIds.isValid(owner.getRemoteConfigurationId()) || RemoteConfigurationIds.needsReconciliation(owner)
                && !Objects.toString(owner.getRemoteError(),"").startsWith(HOLD)) throw changed();
        if(!Set.of("CREATED","PUBLISHED","CODE_IMPORTED").contains(owner.getWorkflowStatus())
                && !RedemptionRewardCheck.pending(owner)) throw changed();
        return new Context(recovery.policySnapshot(issueId),owner.getRemoteConfigurationId());
    }
    private UnifiedRedemptionRemoteExecutorClient.ReuseCheck read(Context c) {var s=c.snapshot();
        return executor().checkReuse(s.accountId(),s.issueId(),c.configurationId(),s.description(),s.claimDate(),s.validFrom(),s.validTo(),s.labels(),s.bonusMin(),s.bonusMax(),s.options(),s.code());}
    private void requireRewardsOnly(UnifiedRedemptionRemoteExecutorClient.ReuseCheck c) {
        if(c==null || c.actualMin()==null || c.actualMax()==null) throw ApiException.conflict("POLICY_READ_UNAVAILABLE","未读到实际奖励，不能修改");
        if(!Set.of("reward_min","reward_max").containsAll(c.differences()))
            throw ApiException.conflict("POLICY_OTHER_FIELDS_DIFFER","远端存在奖励之外的参数差异，未提交修改，请先核对。");
    }
    private View view(RedemptionPolicyUpdate r) {var h=readJson(r.getHistoryJson());return new View(r.getId(),r.getStatus(),r.getReason(),r.getRowVersion(),
            r.getRequestedIssueId(),r.getOwnerIssueId(),r.getConfigurationId(),new BigDecimal(h.get("bonusMin").toString()),new BigDecimal(h.get("bonusMax").toString()),snapshot(r));}
    private RedemptionRecoveryService.Snapshot snapshot(RedemptionPolicyUpdate r) {try{return mapper.readValue(r.getSnapshotJson(),RedemptionRecoveryService.Snapshot.class);}catch(Exception e){throw changed();}}
    private String intent(RedemptionRecoveryService.Snapshot s) {ObjectNode n=mapper.valueToTree(s);n.remove(List.of("issueVersion","ownerVersion","batchVersion","sharedBatches"));return n.toString();}
    private String hash(String s) {try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw changed();}}
    @SuppressWarnings("unchecked") private Map<String,Object> readJson(String s) {try{return mapper.readValue(s,Map.class);}catch(Exception e){throw changed();}}
    private String json(Object o) {try{return mapper.writeValueAsString(o);}catch(Exception e){throw changed();}}
    private void lock(Long a,Long b) {for(Long id:java.util.stream.Stream.of(a,b).distinct().sorted().toList()) em.refresh(issue(id),LockModeType.PESSIMISTIC_WRITE);}
    private RedemptionPolicyUpdate lockedUpdate(Long id) {var r=update(id);em.refresh(r,LockModeType.PESSIMISTIC_WRITE);return r;}
    private RedemptionPolicyUpdate update(Long id) {return updates.findById(id).orElseThrow(()->ApiException.notFound("奖励修改记录"));}
    private RedemptionCodeIssue issue(Long id) {return issues.findById(id).orElseThrow(()->ApiException.notFound("兑换码任务"));}
    private RedemptionCodeBatch batch(Long id) {return batches.findById(id).orElseThrow(()->ApiException.notFound("兑换码批次"));}
    private UnifiedRedemptionRemoteExecutorClient executor() {var c=executors.getIfAvailable();if(c==null) throw changed();return c;}
    private TransactionTemplate tx() {return new TransactionTemplate(tm);}
    private ApiException changed() {return ApiException.conflict("POLICY_STATE_CHANGED","任务、共享范围或参数已变化，请重新核验并确认奖励修改");}
}
