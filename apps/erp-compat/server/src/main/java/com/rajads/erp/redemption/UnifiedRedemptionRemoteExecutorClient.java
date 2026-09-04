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
            RemoteCreationOptions options) {
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
        if (configurationId == null || configurationId.isBlank()) {
            throw new CompatibilityIdentityUnavailableException("统一远端创建服务返回无效结果");
        }
        String groupKey = responseText(body, "remoteGroupKey", "remote_group_key");
        String requestId = responseText(body, "remoteRequestId", "remote_request_id");
        return new CreatedConfiguration(configurationId, groupKey, requestId);
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
                    .timeout(Duration.ofSeconds(45))
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
