package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;

import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/** Shared validation for create receipts, recovery, manual binding and read models. */
final class RemoteConfigurationIds {
    static final String UNCONFIRMED_PREFIX = "远端创建结果未确认";
    static final String AWAITING_REVIEW_PREFIX = UNCONFIRMED_PREFIX + "：待远端主管审核";
    private static final Pattern NUMBER = Pattern.compile("[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?");
    private static final Set<String> NON_IDS = Set.of("null", "none", "true", "false", "nan", "infinity", "-infinity");

    private RemoteConfigurationIds() { }

    static boolean isValid(String raw) {
        if (raw == null) return false;
        String value = raw.trim();
        if (value.isEmpty() || value.length() > 255 || NON_IDS.contains(value.toLowerCase(Locale.ROOT))
                || value.chars().anyMatch(c -> c < 32)) return false;
        // Preserve opaque IDs used by supported adapters; numeric IDs must be positive integers.
        return !NUMBER.matcher(value).matches()
                || (value.matches("[0-9]+") && value.chars().anyMatch(c -> c != '0'));
    }

    static String requireCreated(String value) {
        if (!isValid(value)) throw unconfirmed();
        return value.trim();
    }

    static String requireCreated(String value, String message) {
        if ("-1".equals(value) && message != null && message.contains("触发风控规则")
                && message.contains("需主管审核通过后才可以生成配置")) throw awaitingReview();
        return requireCreated(value);
    }

    static boolean isAwaitingReview(String error) {
        return error != null && error.contains(AWAITING_REVIEW_PREFIX);
    }

    static ApiException awaitingReview() {
        return ApiException.conflict("REMOTE_CREATE_AWAITING_REVIEW", AWAITING_REVIEW_PREFIX
                + "。配置触发风控规则，需主管审核通过后才可以生成配置；请勿重复创建，审核通过后核对配置再登记和发布。");
    }

    static ApiException unconfirmed(RedemptionCodeIssue issue) {
        return isAwaitingReview(issue.getRemoteError()) ? awaitingReview() : unconfirmed();
    }

    static ApiException unconfirmed() {
        return ApiException.conflict("REMOTE_CREATE_RESULT_UNCONFIRMED",
                UNCONFIRMED_PREFIX + "：接口返回无效配置 ID，请先核对远端后台，禁止直接重试。");
    }

    static boolean needsReconciliation(String configurationId, String referenceId, String error) {
        return (configurationId != null && !isValid(configurationId))
                || (referenceId != null && !isValid(referenceId))
                || (error != null && error.contains(UNCONFIRMED_PREFIX));
    }

    static boolean needsReconciliation(RedemptionCodeIssue issue) {
        issue = issue.configurationOwner();
        return needsReconciliation(issue.getRemoteConfigurationId(), issue.getRemoteReferenceId(), issue.getRemoteError())
                || (issue.getRemoteCreateReceiptId() != null && !isValid(issue.getRemoteCreateReceiptId()));
    }

    static void requireUsable(RedemptionCodeIssue issue) {
        RedemptionRewardCheck.requireReady(issue);
        var recovery = RedemptionRecoveryService.summary(issue);
        if (recovery != null && !Set.of("PRESENT", "COMPLETED").contains(recovery.status()))
            throw ApiException.conflict("REMOTE_CONFIGURATION_RECOVERY_REQUIRED", recovery.reason());
        issue = issue.configurationOwner();
        if (needsReconciliation(issue) || !isValid(issue.getRemoteConfigurationId())) throw unconfirmed(issue);
    }
}
