package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;
import jakarta.persistence.EntityManager;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.List;

/** Atomic, idempotent storage of the complete set of codes belonging to one remote configuration. */
@Component
@RequiredArgsConstructor
public class RedemptionCodeStorage {
    private final EntityManager entityManager;

    public int store(RedemptionCodeIssue issue, RedemptionCodeBatch batch, List<String> values) {
        int expected = batch.getRemoteKeyNumber() == null ? 1 : batch.getRemoteKeyNumber();
        List<String> codes = values.stream().map(String::trim).toList();
        if (codes.size() != expected) throw ApiException.badRequest("REDEMPTION_CODE_COUNT_MISMATCH",
                "每组应有 " + expected + " 个兑换码，实际收到 " + codes.size() + " 个");
        if (codes.stream().anyMatch(code -> code.isBlank() || code.length() > 255 || code.contains("\n") || code.contains("\r"))) {
            throw ApiException.badRequest("INVALID_REDEMPTION_CODE", "兑换码格式无效");
        }
        if (new HashSet<>(codes).size() != codes.size()) throw ApiException.badRequest("DUPLICATE_REDEMPTION_CODE", "兑换码文件包含重复号码");
        if (!issue.getCodes().isEmpty()) {
            if (!new HashSet<>(issue.getCodes()).equals(new HashSet<>(codes))) {
                throw ApiException.conflict("REDEMPTION_CODE_LOCKED", "该远端配置已导入其他兑换码，不能覆盖");
            }
            return 0;
        }
        Long conflicts = entityManager.createQuery(
                "select count(distinct i) from RedemptionCodeIssue i left join i.codes code "
                        + "where (code in :codes or i.redemptionCode in :codes) and i.id <> :id", Long.class)
                .setParameter("codes", codes).setParameter("id", issue.getId()).getSingleResult();
        if (conflicts > 0) throw ApiException.conflict("REDEMPTION_CODE_EXISTS", "兑换码已保存到其他任务");
        issue.setCodes(codes);
        return codes.size();
    }
}
