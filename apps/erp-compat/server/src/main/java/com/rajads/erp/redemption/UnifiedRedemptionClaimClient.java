package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.shared.ApiException;
import jakarta.servlet.http.Cookie;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.stream.Collectors;

/** Session-only bridge. All task, account and capability checks also run in the main API. */
@Component
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class UnifiedRedemptionClaimClient {
    private final ObjectMapper mapper;
    private final String base;
    private final String cookieName;
    // Match the main API's HTTP/1.1 transport without attempting h2c upgrades.
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(3))
            .build();

    public UnifiedRedemptionClaimClient(ObjectMapper mapper,
            @Value("${erp.compatibility.remote-executor-url:http://api:8000/api/v1/erp/remote-accounts/compatibility-redemption}") URI base,
            @Value("${erp.compatibility.session-cookie-name:raj_session}") String cookieName) {
        this.mapper = mapper;
        this.base = base.toString() + "/claims";
        this.cookieName = cookieName;
    }

    public JsonNode json(String method, String path, Map<String, String> query, JsonNode payload) {
        try {
            return mapper.readTree(exchange(method, path, query, payload));
        } catch (IOException exception) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "CLAIM_SERVICE_UNAVAILABLE", "领取统计服务返回无效结果");
        }
    }

    public byte[] export(String path, Map<String, String> query) {
        return exchange("GET", path, query, null);
    }

    private byte[] exchange(String method, String path, Map<String, String> query, JsonNode payload) {
        if (!(RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attrs)) {
            throw ApiException.forbidden("领取统计需要统一登录会话");
        }
        String value = null;
        Cookie[] cookies = attrs.getRequest().getCookies();
        if (cookies != null) for (Cookie cookie : cookies) {
            if (cookieName.equals(cookie.getName())) value = cookie.getValue();
        }
        if (value == null || value.contains("\r") || value.contains("\n")) {
            throw ApiException.forbidden("请重新登录后查询领取统计");
        }
        String suffix = query.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(base + path + (suffix.isEmpty() ? "" : "?" + suffix)))
                    .timeout(Duration.ofSeconds(90))
                    .header("Cookie", cookieName + "=" + value)
                    .header("Content-Type", "application/json")
                    .method(method, payload == null ? HttpRequest.BodyPublishers.noBody()
                            : HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(payload))).build();
            HttpResponse<byte[]> response = http.send(request, HttpResponse.BodyHandlers.ofByteArray());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                String detail = "领取统计服务暂不可用";
                try {
                    JsonNode error = mapper.readTree(response.body()).path("detail");
                    if (error.isTextual()) detail = error.asText();
                } catch (IOException ignored) { }
                HttpStatus status = HttpStatus.resolve(response.statusCode());
                throw new ApiException(status == null ? HttpStatus.BAD_GATEWAY : status, "CLAIM_QUERY_FAILED", detail);
            }
            return response.body();
        } catch (IOException exception) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "CLAIM_SERVICE_UNAVAILABLE", "领取统计服务暂不可用");
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "CLAIM_SERVICE_UNAVAILABLE", "领取统计查询已中断");
        }
    }

    private static String encode(String text) {
        return URLEncoder.encode(text, StandardCharsets.UTF_8);
    }
}
