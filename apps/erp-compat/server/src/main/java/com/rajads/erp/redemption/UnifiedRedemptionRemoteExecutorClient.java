package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.identity.CompatibilityIdentityUnavailableException;
import com.rajads.erp.shared.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Executes confirmed redemption operations through the main application's
 * unified RemoteAccount boundary.
 *
 * <p>The compatibility service supplies only its numeric account projection
 * and non-secret task parameters.  The main API resolves that projection,
 * checks the account capability, and decrypts credentials only inside the
 * main process.  This client must never read the legacy connection table.</p>
 */
@Component
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class UnifiedRedemptionRemoteExecutorClient {
    private final ObjectMapper objectMapper;
    private final URI executorUri;
    private final String sessionCookieName;
    private final HttpClient httpClient;

    public UnifiedRedemptionRemoteExecutorClient(
            ObjectMapper objectMapper,
            @Value("${erp.compatibility.remote-executor-url:http://api:8000/api/v1/erp/remote-accounts/compatibility-redemption}") URI executorUri,
            @Value("${erp.compatibility.session-cookie-name:raj_session}") String sessionCookieName) {
        this.objectMapper = objectMapper;
        this.executorUri = executorUri;
        this.sessionCookieName = sessionCookieName;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(3))
                .build();
    }

    public CreatedConfiguration create(
            Long accountId,
            Long issueId,
            String description,
            LocalDate claimDate,
            LocalDate validFrom,
            LocalDate validTo,
            List<Long> labelIds,
            BigDecimal bonusAmount,
            BigDecimal bonusMaxAmount,
            RemoteCreationOptions options,
            String giftCode) {
        if (accountId == null || issueId == null) {
            throw ApiException.badRequest("UNIFIED_REMOTE_CREATE_INVALID", "统一远端创建缺少账号或任务 ID");
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("account_id", accountId);
        payload.put("issue_id", issueId);
        payload.put("description", description);
        payload.put("claim_date", claimDate.toString());
        payload.put("valid_from", validFrom.toString());
        payload.put("valid_to", validTo.toString());
        payload.put("label_ids", labelIds);
        payload.put("bonus_amount", bonusAmount);
        payload.put("bonus_max_amount", bonusMaxAmount);
        payload.put("options", options(options));
        if (giftCode != null) payload.put("gift_code", giftCode);
        // The browser action that called this endpoint is the one confirmed
        // operator action. The main API checks this intent again before it
        // obtains a credential envelope or opens a remote HTTP client.
        payload.put("execution_confirmed", true);
        JsonNode body = postJson(
                "/create",
                payload,
                "统一远端创建服务拒绝了该请求",
                "UNIFIED_REMOTE_CREATE_REJECTED",
                "统一远端创建服务暂时不可用");
        String configurationId = responseText(
                body,
                "remoteConfigurationId",
                "remote_configuration_id");
        configurationId = RemoteConfigurationIds.requireCreated(configurationId);
        String groupKey = responseText(body, "remoteGroupKey", "remote_group_key");
        String requestId = responseText(body, "remoteRequestId", "remote_request_id");
        return new CreatedConfiguration(configurationId, groupKey, requestId);
    }

    public record ReuseCheck(String configurationId, boolean matched, List<String> differences, String groupKey, BigDecimal actualMin, BigDecimal actualMax) {
        public ReuseCheck(String configurationId, boolean matched, List<String> differences) {
            this(configurationId, matched, differences, null, null, null);
        }
        public ReuseCheck(String configurationId, boolean matched, List<String> differences, String groupKey) {
            this(configurationId, matched, differences, groupKey, null, null);
        }
    }

    public record DuplicateCode(String code, String configurationId) { }

    public List<DuplicateCode> checkDuplicateCodes(Long accountId, List<String> codes) {
        var body = postJson("/duplicate-check", Map.of("account_id", accountId, "gift_codes", codes),
                "远端查重失败，本次未创建配置", "REMOTE_DUPLICATE_CHECK_REJECTED", "远端查重未完成，请稍后重试或选择仅本地查重");
        if (!body.path("complete").isBoolean() || !body.path("complete").asBoolean() || !body.path("matches").isArray())
            throw new CompatibilityIdentityUnavailableException("远端查重结果不完整");
        var result = new java.util.ArrayList<DuplicateCode>();
        for (var match : body.path("matches")) {
            String code = match.path("gift_code").asText();
            String id = match.path("configuration_id").asText();
            if (!codes.contains(code) || !RemoteConfigurationIds.isValid(id))
                throw new CompatibilityIdentityUnavailableException("远端查重返回无效配置");
            result.add(new DuplicateCode(code, id));
        }
        return List.copyOf(result);
    }

    public ReuseCheck checkReuse(Long accountId, Long issueId, String configurationId, String description,
            LocalDate claimDate, LocalDate validFrom, LocalDate validTo, List<Long> labelIds,
            BigDecimal bonusMin, BigDecimal bonusMax, RemoteCreationOptions options, String giftCode) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("account_id", accountId);
        payload.put("issue_id", issueId);
        payload.put("remote_configuration_id", configurationId);
        payload.put("description", description);
        payload.put("claim_date", claimDate.toString());
        payload.put("valid_from", validFrom.toString());
        payload.put("valid_to", validTo.toString());
        payload.put("label_ids", labelIds);
        payload.put("bonus_amount", bonusMin);
        payload.put("bonus_max_amount", bonusMax);
        payload.put("options", options(options));
        payload.put("gift_code", giftCode);
        JsonNode body = postJson("/reuse-check", payload, "远端复用核验被拒绝",
                "REMOTE_REUSE_CHECK_REJECTED", "远端复用核验暂时不可用");
        return decodeReuseCheck(body, configurationId);
    }

    private ReuseCheck decodeReuseCheck(JsonNode body, String configurationId) {
        String returnedId = responseText(body, "remoteConfigurationId", "remote_configuration_id");
        if (!configurationId.equals(returnedId) || !body.path("matched").isBoolean()
                || !body.path("differences").isArray()) {
            throw new CompatibilityIdentityUnavailableException("远端复用核验返回无效结果");
        }
        List<String> differences = new java.util.ArrayList<>();
        for (var field : body.path("differences")) {
            if (!field.isTextual()) throw new CompatibilityIdentityUnavailableException("远端复用核验返回无效差异");
            differences.add(field.asText());
        }
        boolean matched = body.path("matched").asBoolean();
        if (matched != differences.isEmpty()) throw new CompatibilityIdentityUnavailableException("远端复用核验结果不一致");
        return new ReuseCheck(returnedId, matched, List.copyOf(differences), responseText(body, "remoteGroupKey", "remote_group_key"),
                responseAmount(body,"actualBonusAmount","actual_bonus_amount"), responseAmount(body,"actualBonusMaxAmount","actual_bonus_max_amount"));
    }

    public JsonNode deletion(Long accountId,Long issueId,String configurationId,String operation,String fingerprint) {
        var payload=new LinkedHashMap<String,Object>(); payload.put("account_id",accountId);payload.put("issue_id",issueId);
        payload.put("remote_configuration_id",configurationId);
        if (fingerprint!=null) payload.put("expected_fingerprint",fingerprint);
        payload.put("execution_confirmed","execute".equals(operation));
        boolean permission = "permission".equals(operation);
        var result=postJson("/deletion/"+operation,payload,
                permission ? "账号删除能力检查未通过" : "远端删除操作被拒绝",
                permission ? "DELETE_PERMISSION_REJECTED" : "REMOTE_DELETE_REJECTED",
                "execute".equals(operation) ? "远端删除结果待核对，请勿重复提交" : "删除前检查暂不可用，请稍后重新预检；尚未提交删除");
        if ("permission".equals(operation)) { if(!result.path("allowed").asBoolean()) throw ApiException.conflict("DELETE_NOT_AUTHORIZED","账号未获删除能力"); }
        else if (!configurationId.equals(result.path("configurationId").asText()) || !java.util.Set.of("PRESENT","ABSENT").contains(result.path("state").asText()))
            throw ApiException.conflict("REMOTE_DELETE_INVALID_RESPONSE","删除核验响应不完整");
        return result;
    }

    public void requireRewardUpdateCapability(Long accountId, Long issueId) {
        var result = postJson("/reward-update/permission", Map.of("account_id", accountId, "issue_id", issueId),
                "账号缺少独立奖励修改及回读能力，未提交修改", "REWARD_UPDATE_NOT_AUTHORIZED", "奖励修改授权核验不可用");
        if (!result.path("allowed").isBoolean() || !result.path("allowed").asBoolean())
            throw ApiException.conflict("REWARD_UPDATE_NOT_AUTHORIZED", "奖励修改能力未确认，未提交修改");
    }

    public ReuseCheck updateReward(RedemptionRecoveryService.Snapshot snapshot, String configurationId) {
        var payload = expectation(snapshot, configurationId); payload.put("execution_confirmed", true);
        var body = postJson("/reward-update", payload, "远端奖励修改被拒绝", "REMOTE_REWARD_UPDATE_REJECTED", "奖励修改结果待核对");
        var result = decodeReuseCheck(body, configurationId);
        if (!result.matched() || result.actualMin() == null || result.actualMax() == null
                || result.actualMin().compareTo(snapshot.bonusMin()) != 0 || result.actualMax().compareTo(snapshot.bonusMax()) != 0)
            throw new CompatibilityIdentityUnavailableException("奖励修改回读未匹配，结果待核对");
        return result;
    }
    private BigDecimal responseAmount(JsonNode body, String camel, String snake) {
        var node = body.has(camel) ? body.path(camel) : body.path(snake);
        if (node.isMissingNode() || node.isNull()) return null;
        if (!node.isTextual() && !node.isNumber()) throw new CompatibilityIdentityUnavailableException("实际奖励回读无效");
        try { return new BigDecimal(node.asText()); }
        catch (NumberFormatException exception) { throw new CompatibilityIdentityUnavailableException("实际奖励回读无效"); }
    }

    public record RecoveryCheck(String configurationId, String state, java.time.Instant checkedAt, int scannedRows, int scannedPages) {
        public RecoveryCheck(String configurationId, String state, java.time.Instant checkedAt) { this(configurationId, state, checkedAt, 0, 1); }
    }

    public RecoveryCheck checkRecovery(RedemptionRecoveryService.Snapshot snapshot, String configurationId,
            String groupKey, boolean checkInventory) {
        Map<String, Object> payload = expectation(snapshot, configurationId);
        payload.put("remote_group_key", groupKey);
        payload.put("check_inventory", checkInventory);
        JsonNode body = postJson("/recovery-check", payload, "远端缺失核验被拒绝",
                "REMOTE_RECOVERY_CHECK_REJECTED", "远端缺失核验暂时不可用");
        String id = responseText(body, "remoteConfigurationId", "remote_configuration_id");
        String state = responseText(body, "state", "state");
        try {
            var checkedAt = java.time.Instant.parse(responseText(body, "checkedAt", "checked_at"));
            if (!configurationId.equals(id) || !java.util.Set.of("ABSENT", "PRESENT", "CODE_EXISTS").contains(state)
                    || checkedAt.isBefore(java.time.Instant.now().minusSeconds(60))
                    || checkedAt.isAfter(java.time.Instant.now().plusSeconds(5))) throw new IllegalArgumentException();
            int rows = (body.has("scannedRows") ? body.path("scannedRows") : body.path("scanned_rows")).asInt(-1);
            int pages = (body.has("scannedPages") ? body.path("scannedPages") : body.path("scanned_pages")).asInt(-1);
            if ("ABSENT".equals(state) && (!(body.has("scannedRows") ? body.path("scannedRows") : body.path("scanned_rows")).isIntegralNumber()
                    || !(body.has("scannedPages") ? body.path("scannedPages") : body.path("scanned_pages")).isIntegralNumber()
                    || rows < 0 || pages < 1 || pages > 200)) throw new IllegalArgumentException();
            return new RecoveryCheck(id, state, checkedAt, rows, pages);
        } catch (RuntimeException exception) {
            throw new CompatibilityIdentityUnavailableException("远端缺失核验返回无效或过期结果");
        }
    }

    private Map<String, Object> expectation(RedemptionRecoveryService.Snapshot s, String configurationId) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("account_id", s.accountId()); payload.put("issue_id", s.issueId());
        payload.put("remote_configuration_id", configurationId); payload.put("description", s.description());
        payload.put("claim_date", s.claimDate().toString()); payload.put("valid_from", s.validFrom().toString());
        payload.put("valid_to", s.validTo().toString()); payload.put("label_ids", s.labels());
        payload.put("bonus_amount", s.bonusMin()); payload.put("bonus_max_amount", s.bonusMax());
        payload.put("options", options(s.options())); payload.put("gift_code", s.code());
        return payload;
    }

    public record AbsenceCheck(String giftCode, int scannedRows, int scannedPages, String checkedAt) { }

    public AbsenceCheck checkAbsence(Long accountId, Long issueId, String giftCode) {
        JsonNode body = postJson("/absence-check", Map.of("account_id", accountId,
                "issue_id", issueId, "gift_code", giftCode), "远端兑换码不存在性核验被拒绝",
                "REMOTE_ABSENCE_CHECK_REJECTED", "远端兑换码目录暂时无法完整核验");
        String returnedCode = responseText(body, "giftCode", "gift_code");
        JsonNode absent = body.has("confirmedAbsent") ? body.path("confirmedAbsent") : body.path("confirmed_absent");
        JsonNode rows = body.has("scannedRows") ? body.path("scannedRows") : body.path("scanned_rows");
        JsonNode pages = body.has("scannedPages") ? body.path("scannedPages") : body.path("scanned_pages");
        String checkedAt = responseText(body, "checkedAt", "checked_at");
        if (!giftCode.equalsIgnoreCase(returnedCode) || !absent.isBoolean() || !absent.booleanValue()
                || !rows.isInt() || rows.intValue() < 0 || !pages.isInt() || pages.intValue() < 1
                || pages.intValue() > 200 || checkedAt == null) {
            throw new CompatibilityIdentityUnavailableException("远端不存在性核验返回无效结果");
        }
        try {
            java.time.Instant instant = java.time.Instant.parse(checkedAt);
            if (instant.isBefore(java.time.Instant.now().minusSeconds(60)) || instant.isAfter(java.time.Instant.now().plusSeconds(10)))
                throw new IllegalArgumentException("Stale absence result");
        } catch (RuntimeException invalid) {
            throw new CompatibilityIdentityUnavailableException("远端不存在性核验时间无效");
        }
        return new AbsenceCheck(returnedCode, rows.intValue(), pages.intValue(), checkedAt);
    }

    public PublishedBatch publish(
            Long accountId,
            Long batchId,
            String publishEnvironment,
            boolean scheduled,
            LocalDateTime scheduledTime,
            boolean fallbackToScheduled) {
        if (accountId == null || batchId == null) {
            throw ApiException.badRequest("UNIFIED_REMOTE_PUBLISH_INVALID", "统一远端发布缺少账号或批次 ID");
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("account_id", accountId);
        payload.put("batch_id", batchId);
        payload.put("publish_environment", publishEnvironment);
        payload.put("mode", scheduled ? "SCHEDULED" : "IMMEDIATE");
        if (scheduledTime != null) payload.put("scheduled_time", scheduledTime.toString());
        payload.put("fallback_to_scheduled", fallbackToScheduled);
        payload.put("execution_confirmed", true);
        JsonNode body = postJson(
                "/publish",
                payload,
                "统一远端发布服务拒绝了该请求",
                "UNIFIED_REMOTE_PUBLISH_REJECTED",
                "统一远端发布服务暂时不可用");
        String taskId = responseText(body, "remotePublishTaskId", "remote_publish_task_id");
        if (taskId == null || taskId.isBlank()) {
            throw new CompatibilityIdentityUnavailableException("统一远端发布服务返回无效结果");
        }
        return new PublishedBatch(
                taskId,
                responseText(body, "remoteRequestId", "remote_request_id"));
    }

    public record ConfigurationReference(String configuration_id, String group_key, int key_number) { }
    public record ConfigurationVerification(String configurationId, String state) { }
    public record PublicationVerification(String remotePublishTaskId, Integer remoteStatus,
            String publicationState, boolean canCancel, List<ConfigurationVerification> configurations, String checkedAt, String configurationError) { }

    public PublicationVerification verifyPublication(Long accountId, Long batchId, String taskId,
            String environment, List<ConfigurationReference> configurations) {
        JsonNode body = postJson("/verify", Map.of("account_id", accountId, "batch_id", batchId,
                "remote_publish_task_id", taskId, "publish_environment", environment, "configurations", configurations),
                "远端状态核验被拒绝", "UNIFIED_REMOTE_VERIFY_REJECTED", "远端状态暂时无法核验");
        String returnedId = responseText(body, "remotePublishTaskId", "remote_publish_task_id");
        String state = responseText(body, "publicationState", "publication_state");
        String checkedAt = responseText(body, "checkedAt", "checked_at");
        if (!taskId.equals(returnedId) || state == null || checkedAt == null
                || !java.util.Set.of("WAITING", "RUNNING", "FAILED", "COMPLETED", "CANCELLED", "UNKNOWN").contains(state)
                || !body.path("configurations").isArray()) {
            throw new CompatibilityIdentityUnavailableException("远端状态核验返回无效结果");
        }
        List<ConfigurationVerification> verified = new java.util.ArrayList<>();
        for (JsonNode item : body.path("configurations")) verified.add(new ConfigurationVerification(
                responseText(item, "configurationId", "configuration_id"), item.path("state").asText()));
        JsonNode remoteStatus = body.has("remoteStatus") ? body.path("remoteStatus") : body.path("remote_status");
        boolean canCancel = body.has("canCancel") ? body.path("canCancel").asBoolean() : body.path("can_cancel").asBoolean();
        return new PublicationVerification(returnedId, remoteStatus.isInt() ? remoteStatus.intValue() : null,
                state, "WAITING".equals(state) && canCancel, List.copyOf(verified), checkedAt, responseText(body, "configurationError", "configuration_error"));
    }

    public void cancelScheduledPublish(Long accountId, Long batchId, String taskId) {
        if (accountId == null || batchId == null || taskId == null || taskId.isBlank()) {
            throw ApiException.badRequest("UNIFIED_REMOTE_CANCEL_INVALID", "统一远端撤销缺少账号、批次或发布任务 ID");
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("account_id", accountId);
        payload.put("batch_id", batchId);
        payload.put("remote_publish_task_id", taskId);
        payload.put("execution_confirmed", true);
        JsonNode body = postJson("/cancel", payload, "统一远端撤销服务拒绝了该请求",
                "UNIFIED_REMOTE_CANCEL_REJECTED", "统一远端撤销服务暂时不可用");
        if (!body.path("cancelled").isBoolean() || !body.path("cancelled").booleanValue()) {
            throw new CompatibilityIdentityUnavailableException("统一远端撤销服务未确认撤销成功");
        }
    }

    public DownloadedCodes download(Long accountId, Long issueId, String configurationId, String groupKey, int keyNumber) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("account_id", accountId);
        payload.put("issue_id", issueId);
        payload.put("remote_configuration_id", configurationId);
        payload.put("remote_group_key", groupKey);
        payload.put("key_number", keyNumber);
        payload.put("execution_confirmed", true);
        JsonNode body = postJson("/download", payload, "统一远端下载服务拒绝了该请求",
                "UNIFIED_REMOTE_DOWNLOAD_REJECTED", "统一远端下载服务暂时不可用");
        JsonNode codes = body.has("redemptionCodes") ? body.path("redemptionCodes") : body.path("redemption_codes");
        if (!codes.isArray() || codes.isEmpty()) throw new CompatibilityIdentityUnavailableException("统一远端下载返回无效结果");
        List<String> values = new java.util.ArrayList<>();
        for (JsonNode code : codes) {
            if (!code.isTextual() || code.asText().isBlank()) throw new CompatibilityIdentityUnavailableException("统一远端下载返回无效兑换码");
            values.add(code.asText());
        }
        return new DownloadedCodes(List.copyOf(values), responseText(body, "remoteGroupKey", "remote_group_key"));
    }

    public record DownloadedCodes(List<String> codes, String groupKey) { }

    private Map<String, Object> options(RemoteCreationOptions options) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("publish_environment", options.publishEnvironment());
        result.put("flow_times", options.flowTimes());
        result.put("activity_recharge", options.activityRecharge());
        result.put("activity_recharge_count", options.activityRechargeCount());
        result.put("activity_id", options.activityId());
        result.put("key_number", options.keyNumber());
        result.put("single_user_limit", options.singleUserLimit());
        result.put("single_key_limit", options.singleKeyLimit());
        result.put("require_bind_bank_card", options.requireBindBankCard());
        result.put("require_bind_phone", options.requireBindPhone());
        result.put("check_uuid", options.checkUuid());
        result.put("uuid_reward_limit", options.uuidRewardLimit());
        result.put("check_login_ip", options.checkLoginIp());
        result.put("login_ip_reward_limit", options.loginIpRewardLimit());
        result.put("check_register_ip", options.checkRegisterIp());
        result.put("register_ip_reward_limit", options.registerIpRewardLimit());
        return result;
    }

    private JsonNode postJson(
            String suffix,
            Object payload,
            String rejectedDetail,
            String rejectedCode,
            String unavailableDetail) {
        String cookieValue = sessionCookie();
        if (cookieValue == null || cookieValue.isBlank() || containsHeaderBreak(cookieValue)) {
            throw new CompatibilityIdentityUnavailableException("缺少统一登录会话");
        }
        try {
            URI uri = URI.create(executorUri.toString().replaceAll("/$", "") + suffix);
            HttpRequest request = HttpRequest.newBuilder(uri)
                    .timeout(Duration.ofSeconds(suffix.startsWith("/deletion/") || suffix.equals("/duplicate-check") ? 90 : 45))
                    .header("Accept", "application/json")
                    .header("Content-Type", "application/json")
                    .header("Cookie", sessionCookieName + "=" + cookieValue)
                    .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(payload)))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw remoteError(response, rejectedDetail, rejectedCode, unavailableDetail);
            }
            return objectMapper.readTree(response.body());
        } catch (ApiException | CompatibilityIdentityUnavailableException exception) {
            throw exception;
        } catch (IOException exception) {
            throw new CompatibilityIdentityUnavailableException(unavailableDetail, exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new CompatibilityIdentityUnavailableException(unavailableDetail, exception);
        }
    }

    private ApiException remoteError(
            HttpResponse<String> response,
            String rejectedDetail,
            String rejectedCode,
            String unavailableDetail) {
        String detail = rejectedDetail;
        try {
            JsonNode body = objectMapper.readTree(response.body());
            String value = text(body.path("detail"));
            if (value != null) detail = value;
        } catch (IOException ignored) {
            // Retain the safe generic failure for malformed downstream data.
        }
        HttpStatus status = HttpStatus.resolve(response.statusCode());
        if (status == null || status.is5xxServerError()) {
            throw new CompatibilityIdentityUnavailableException(unavailableDetail);
        }
        return new ApiException(status, rejectedCode, detail);
    }

    private String sessionCookie() {
        if (!(RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attributes)) {
            throw ApiException.forbidden("统一登录会话仅能在已认证的 ERP 请求中使用");
        }
        HttpServletRequest request = attributes.getRequest();
        Cookie[] cookies = request.getCookies();
        if (cookies == null) return null;
        for (Cookie cookie : cookies) if (sessionCookieName.equals(cookie.getName())) return cookie.getValue();
        return null;
    }

    private static String text(JsonNode node) {
        return node != null && node.isTextual() && !node.asText().isBlank() ? node.asText() : null;
    }

    private static String responseText(JsonNode body, String apiField, String legacyField) {
        String value = text(body.path(apiField));
        return value != null ? value : text(body.path(legacyField));
    }

    private static boolean containsHeaderBreak(String value) {
        return value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0;
    }

    public record CreatedConfiguration(String configurationId, String groupKey, String requestId) { }

    public record PublishedBatch(String taskId, String requestId) { }
}
