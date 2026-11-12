package com.rajads.erp.redemption;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/** Progress follows canonical configuration facts, including facts shared with other tasks. */
@Component
@RequiredArgsConstructor
public class RedemptionBatchProgress {
    private final RedemptionCodeIssueRepository issues;
    private final RedemptionCodeBatchRepository batches;

    public void refresh(RedemptionCodeBatch batch) {
        var rows = issues.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batch.getId());
        if (rows.stream().anyMatch(i -> RedemptionRewardCheck.PENDING.contains(i.getEffectiveWorkflowStatus()))) {
            if (!"CREATING".equals(batch.getStatus())) { batch.setStatus("CREATING"); batches.save(batch); }
            return;
        }
        boolean complete = rows.size() == batch.getExpectedCodeCount();
        boolean valid = complete && rows.stream().noneMatch(RemoteConfigurationIds::needsReconciliation)
                && rows.stream().allMatch(i -> java.util.Set.of("CREATED", "PUBLISHED", "CODE_IMPORTED")
                        .contains(i.getEffectiveWorkflowStatus()));
        String status;
        if (valid && rows.stream().allMatch(i -> "CODE_IMPORTED".equals(i.getEffectiveWorkflowStatus()))) status = "COMPLETED";
        else if (!valid) status = "CREATING";
        else if ("CREATING".equals(batch.getStatus()) && batch.getPublishedAt() != null
                && rows.stream().anyMatch(i -> "CREATED".equals(i.getEffectiveWorkflowStatus()))) status = "CREATING";
        else if (batch.getRemotePublishTaskId() != null && !batch.getRemotePublishTaskId().startsWith("PENDING:")
                || rows.stream().noneMatch(i -> "CREATED".equals(i.getEffectiveWorkflowStatus()))) status = "PUBLISHED";
        else status = "READY_TO_PUBLISH";
        if (!status.equals(batch.getStatus())) { batch.setStatus(status); batches.save(batch); }
    }

    public void refreshRelated(Long ownerId) {
        for (Long batchId : issues.findRelatedBatchIds(ownerId)) {
            if (batchId != null) batches.findById(batchId).ifPresent(this::refresh);
        }
    }
}
