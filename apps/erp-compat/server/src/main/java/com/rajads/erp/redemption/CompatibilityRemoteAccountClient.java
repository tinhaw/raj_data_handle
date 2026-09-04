package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.identity.CompatibilityIdentityUnavailableException;
import com.rajads.erp.shared.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.math.BigDecimal;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.List;

/**
 * Read/write bridge for the secret-free, local remote-account metadata owned
 * by the main API.  It never calls a Raj backend or accesses credentials.
 */
@Component
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilityRemoteAccountClient {
    private final ObjectMapper objectMapper;
    private final URI remoteAccountsUri;
    private final HttpClient httpClient;

    public CompatibilityRemoteAccountClient(
            ObjectMapper objectMapper,
            @Value("${erp.compatibility.remote-accounts-url:http://api:8000/api/v1/erp/remote-accounts}") URI remoteAccountsUri) {
        this.objectMapper = objectMapper;
        this.remoteAccountsUri = remoteAccountsUri;
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
    }

    public TagSnapshot tags(String accountId, String cookieName, String cookieValue) {
        return request(accountId, cookieName, cookieValue, "GET", null, TagSnapshot.class, "/tags");
    }

    public RewardTierPreset rewardTierPreset(String accountId, String cookieName, String cookieValue) {
        return request(accountId, cookieName, cookieValue, "GET", null, RewardTierPreset.class, "/reward-tier-preset");
    }

    public RewardTierPreset saveRewardTierPreset(
            String accountId,
            String cookieName,
            String cookieValue,
            RedemptionDtos.RewardTierPresetSaveRequest request) {
        return request(accountId, cookieName, cookieValue, "PUT", request, RewardTierPreset.class, "/reward-tier-preset");
    }

    private <T> T request(
            String accountId,
            String cookieName,
            String cookieValue,
            String method,
            Object payload,
            Class<T> responseType,
            String suffix) {
        if (accountId == null || accountId.isBlank()) throw ApiException.notFound("远端账号");
        if (cookieValue == null || cookieValue.isBlank() || containsHeaderBreak(cookieValue)) {
            throw new CompatibilityIdentityUnavailableException("缺少统一登录会话");
        }
        try {
            URI uri = URI.create(remoteAccountsUri.toString().replaceAll("/$", "") + "/"
                    + URLEncoder.encode(accountId, StandardCharsets.UTF_8) + suffix);
            HttpRequest.Builder request = HttpRequest.newBuilder(uri)
                    .timeout(Duration.ofSeconds(5))
                    .header("Accept", "application/json")
                    .header("Cookie", cookieName + "=" + cookieValue);
            if (payload == null) {
                request.method(method, HttpRequest.BodyPublishers.noBody());
            } else {
                request.header("Content-Type", "application/json")
                        .method(method, HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(payload)));
            }
            HttpResponse<String> response = httpClient.send(request.build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() >= 200 && response.statusCode() < 300) {
                return objectMapper.readValue(response.body(), responseType);
            }
            throw remoteAccountError(response);
        } catch (ApiException | CompatibilityIdentityUnavailableException exception) {
            throw exception;
        } catch (IOException exception) {
            throw new CompatibilityIdentityUnavailableException("统一远端账号服务暂时不可用", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new CompatibilityIdentityUnavailableException("统一远端账号服务读取被中断", exception);
        }
    }

    private ApiException remoteAccountError(HttpResponse<String> response) {
        String detail = "统一远端账号服务暂时不可用";
        try {
            JsonNode body = objectMapper.readTree(response.body());
            JsonNode value = body.path("detail");
            if (value.isTextual() && !value.asText().isBlank()) detail = value.asText();
        } catch (IOException ignored) {
            // Retain the safe generic message for malformed downstream errors.
        }
        HttpStatus status = HttpStatus.resolve(response.statusCode());
        if (status == null || status.is5xxServerError()) {
            throw new CompatibilityIdentityUnavailableException("统一远端账号服务暂时不可用");
        }
        return new ApiException(status, "REMOTE_ACCOUNT_METADATA_REJECTED", detail);
    }

    private boolean containsHeaderBreak(String value) {
        return value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0;
    }

    public record RemoteTag(Long id, String name) { }

    public record TagSnapshot(boolean exists, List<RemoteTag> tags, String source, boolean stale,
                              Instant syncedAt, Instant updatedAt, Long rowVersion) { }

    public record RewardTierPresetTier(String userType, List<Long> labelIds, String displayName, BigDecimal minDepositAmount,
                                       BigDecimal bonusAmount, BigDecimal bonusMaxAmount) { }

    public record RewardTierPreset(boolean exists, boolean stale, List<RewardTierPresetTier> tiers,
                                   List<RemoteTag> tagSnapshot, Instant savedAt, Long rowVersion) { }
}
