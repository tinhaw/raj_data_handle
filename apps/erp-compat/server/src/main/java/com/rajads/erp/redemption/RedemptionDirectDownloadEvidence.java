package com.rajads.erp.redemption;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.audit.AuditLogRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

@Component
@RequiredArgsConstructor
class RedemptionDirectDownloadEvidence {
    private final AuditLogRepository auditLogs;
    private final ObjectMapper mapper;

    boolean allImportedDirectly(Long batchId, List<RedemptionCodeIssue> rows) {
        Map<String, RedemptionCodeIssue> pending = rows.stream()
                .filter(row -> "CODE_IMPORTED".equals(row.getEffectiveWorkflowStatus()))
                .collect(Collectors.toMap(row -> row.getId().toString(), row -> row));
        if (pending.isEmpty()) return false;
        var logs = auditLogs.findByActionAndEntityTypeAndEntityIdInOrderByIdDesc(
                "REDEMPTION_REMOTE_CODE_DOWNLOADED", "REDEMPTION_CODE_ISSUE", pending.keySet());
        for (var log : logs) {
            var requested = pending.remove(log.getEntityId());
            if (requested == null) continue;
            var owner = requested.configurationOwner();
            if (owner.getGeneratedAt() == null || log.getCreatedAt().isBefore(owner.getGeneratedAt())
                    || owner.getRemoteConfigurationId() == null
                    || !Objects.equals(owner.getInventoryConfigurationId(), owner.getRemoteConfigurationId())
                    || log.getAfterJson() == null) return false;
            try {
                var facts = mapper.readTree(log.getAfterJson());
                if (facts == null || !facts.path("withoutPublication").isBoolean() || !facts.path("withoutPublication").booleanValue()
                        || facts.path("batchId").asLong(-1) != batchId || facts.path("ownerIssueId").asLong(-1) != owner.getId()
                        || !owner.getRemoteConfigurationId().equals(facts.path("remoteConfigurationId").textValue())) return false;
            } catch (JsonProcessingException invalidEvidence) {
                return false;
            }
        }
        return pending.isEmpty();
    }
}
