package com.rajads.erp.identity;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Optional;

/** Validates the existing HttpOnly session through the main FastAPI authority. */
@Component
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilityIdentityClient {
    private final ObjectMapper objectMapper;
    private final URI identityUri;
    private final HttpClient httpClient;

    public CompatibilityIdentityClient(
            ObjectMapper objectMapper,
            @Value("${erp.compatibility.identity-url}") URI identityUri) {
        this.objectMapper = objectMapper;
        this.identityUri = identityUri;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(3))
                .build();
    }

    public Optional<CompatibilityIdentity> resolve(String cookieName, String cookieValue) {
        if (cookieValue == null || cookieValue.isBlank() || containsHeaderBreak(cookieValue)) return Optional.empty();
        HttpRequest request = HttpRequest.newBuilder(identityUri)
                .timeout(Duration.ofSeconds(5))
                .header("Accept", "application/json")
                .header("Cookie", cookieName + "=" + cookieValue)
                .GET()
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() == 401 || response.statusCode() == 403) return Optional.empty();
            if (response.statusCode() != 200) {
                throw new CompatibilityIdentityUnavailableException("统一身份服务暂时不可用");
            }
            return Optional.of(objectMapper.readValue(response.body(), CompatibilityIdentity.class));
        } catch (IOException exception) {
            throw new CompatibilityIdentityUnavailableException("统一身份服务暂时不可用", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new CompatibilityIdentityUnavailableException("统一身份校验被中断", exception);
        }
    }

    private boolean containsHeaderBreak(String value) {
        return value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0;
    }
}
