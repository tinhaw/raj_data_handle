package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;
import jakarta.persistence.EntityManager;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/** Atomic, idempotent storage of the complete set of codes belonging to one remote configuration. */
@Component
@RequiredArgsConstructor
public class RedemptionCodeStorage {
    private final EntityManager entityManager;

    public int store(RedemptionCodeIssue issue, RedemptionCodeBatch batch, List<String> values) {
        return store(issue, batch, values, false);
    }

    /** Only the verified native download path may admit another special-code generation. */
    int storeDownloaded(RedemptionCodeIssue issue, RedemptionCodeBatch batch, List<String> values) {
        return store(issue, batch, values, true);
    }

    private int store(RedemptionCodeIssue issue, RedemptionCodeBatch batch, List<String> values, boolean downloaded) {
        RedemptionRewardCheck.requireReady(issue);
        if (issue.getReusedFromIssue() != null) throw new IllegalArgumentException("Only a canonical owner may store codes");
        int expected = RedemptionRemoteOperationService.effectiveKeyNumber(issue, batch);
        List<String> codes = values.stream().map(String::trim).toList();
        if (codes.size() != expected) throw ApiException.badRequest("REDEMPTION_CODE_COUNT_MISMATCH",
                "每组应有 " + expected + " 个兑换码，实际收到 " + codes.size() + " 个");
        if (codes.stream().anyMatch(code -> code.isBlank() || code.length() > 255 || code.contains("\n") || code.contains("\r"))) {
            throw ApiException.badRequest("INVALID_REDEMPTION_CODE", "兑换码格式无效");
        }
        List<String> normalized = codes.stream().map(code -> code.toLowerCase(Locale.ROOT)).toList();
        if (new HashSet<>(normalized).size() != codes.size()) throw ApiException.badRequest("DUPLICATE_REDEMPTION_CODE", "兑换码文件包含重复号码");
        var recovery = issue.getCurrentRecovery();
        boolean generationImport = recovery != null && "COMPLETED".equals(recovery.getStatus())
                && !"GENERATED".equals(issue.getState()) && recovery.getNewConfigurationId().equals(issue.getRemoteConfigurationId());
        if (!generationImport && !issue.getCodes().isEmpty()) {
            if (!new HashSet<>(issue.getCodes()).equals(new HashSet<>(codes))) {
                throw ApiException.conflict("REDEMPTION_CODE_LOCKED", "该远端配置已导入其他兑换码，不能覆盖");
            }
            return 0;
        }
        var conflicts = entityManager.createQuery(
                "select distinct i from RedemptionCodeIssue i left join i.codes code "
                        + "where i.remoteMarketId = :market and (lower(code.value) in :codes or lower(i.redemptionCode) in :codes) and i.id <> :id", RedemptionCodeIssue.class)
                .setParameter("codes", normalized).setParameter("id", issue.getId())
                .setParameter("market", issue.getRemoteMarketId()).getResultList();
        var historicalConflicts = entityManager.createQuery(
                "select h from RedemptionHistoricalCode h where h.remoteMarketId = :market and lower(h.code) in :codes and h.ownerIssueId <> :id", RedemptionHistoricalCode.class)
                .setParameter("codes", normalized).setParameter("id", issue.getId()).setParameter("market", issue.getRemoteMarketId()).getResultList();
        boolean separateGeneration = downloaded && expected == 1 && nativeId(issue.getRemoteConfigurationId())
                && specialCodeMatches(issue, batch, codes.get(0));
        for (var other : conflicts) {
            String otherConfiguration = other.getInventoryConfigurationId() == null
                    ? other.getRemoteConfigurationId() : other.getInventoryConfigurationId();
            if (!separateGeneration || !differentSpecialGeneration(other, otherConfiguration, issue.getRemoteConfigurationId(), codes.get(0)))
                throw collision();
        }
        for (var history : historicalConflicts) {
            var other = entityManager.find(RedemptionCodeIssue.class, history.getOwnerIssueId());
            if (!separateGeneration || !differentSpecialGeneration(other, history.getConfigurationId(), issue.getRemoteConfigurationId(), codes.get(0)))
                throw collision();
        }
        // Bind the inventory to the exact configuration before Hibernate writes the head and collection.
        // Recovery retains the old generation in history; aliases never receive their own copy.
        issue.setInventoryConfigurationId(issue.getRemoteConfigurationId());
        issue.setCodes(codes);
        return codes.size();
    }
    private boolean differentSpecialGeneration(RedemptionCodeIssue other, String oldConfiguration, String configuration, String code) {
        if (other == null || other.getReusedFromIssue() != null || !nativeId(oldConfiguration)
                || Objects.equals(oldConfiguration, configuration) || other.getBatchId() == null) return false;
        return specialCodeMatches(other, entityManager.find(RedemptionCodeBatch.class, other.getBatchId()), code);
    }

    private static boolean specialCodeMatches(RedemptionCodeIssue issue, RedemptionCodeBatch batch, String code) {
        return batch != null && batch.getRedemptionType().usesSpecialCode()
                && Objects.equals(batch.getRemoteKeyNumber(), 1) && issue.getClaimDate() != null
                && issue.getMinDepositAmount() != null
                && batch.specialCode(issue.getClaimDate(), issue.getMinDepositAmount()).equalsIgnoreCase(code);
    }

    private static boolean nativeId(String value) { return value != null && value.matches("[1-9][0-9]*"); }

    private static ApiException collision() {
        return ApiException.conflict("REDEMPTION_CODE_EXISTS", "兑换码已保存到其他任务，且未核实为不同远端配置的特殊码；请核对配置身份后重试下载");
    }
}
