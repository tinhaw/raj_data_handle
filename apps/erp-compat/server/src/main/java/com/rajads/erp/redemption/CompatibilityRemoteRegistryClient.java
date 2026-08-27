package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.identity.CompatibilityIdentityUnavailableException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

@Component
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilityRemoteRegistryClient {
    private final ObjectMapper objectMapper;
    private final URI registryUri;
    private final HttpClient httpClient;

    public CompatibilityRemoteRegistryClient(
            ObjectMapper objectMapper,
            @Value("${erp.compatibility.remote-registry-url}") URI registryUri) {
        this.objectMapper = objectMapper;
        this.registryUri = registryUri;
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
    }

    public CompatibilityRemoteRegistry get(String cookieName, String cookieValue) {
        if (cookieValue == null || cookieValue.isBlank() || cookieValue.indexOf('\r') >= 0 || cookieValue.indexOf('\n') >= 0) {
            throw new CompatibilityIdentityUnavailableException("缺少统一登录会话");
        }
        HttpRequest request = HttpRequest.newBuilder(registryUri)
                .timeout(Duration.ofSeconds(5))
                .header("Accept", "application/json")
                .header("Cookie", cookieName + "=" + cookieValue)
                .GET()
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                throw new CompatibilityIdentityUnavailableException("统一远端账号注册表不可用");
            }
            return objectMapper.readValue(response.body(), CompatibilityRemoteRegistry.class);
        } catch (IOException exception) {
            throw new CompatibilityIdentityUnavailableException("统一远端账号注册表不可用", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new CompatibilityIdentityUnavailableException("统一远端账号注册表读取被中断", exception);
        }
    }
}
