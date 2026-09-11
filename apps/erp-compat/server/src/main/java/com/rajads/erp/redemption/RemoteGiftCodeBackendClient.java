package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.shared.ApiException;
import lombok.RequiredArgsConstructor;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.DataFormatter;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.springframework.orm.ObjectOptimisticLockingFailureException;
import org.springframework.stereotype.Component;

import java.io.ByteArrayInputStream;
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
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Base64;
import java.util.*;

/** Exact adapter for the remote gift-code configuration, publish and export APIs supplied by operations. */
@Component
@RequiredArgsConstructor
public class RemoteGiftCodeBackendClient {
    private static final DateTimeFormatter REMOTE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private final ObjectMapper objectMapper;
    private final RemoteConnectionCredentialCipher credentialCipher;
    private final RedemptionRemoteConnectionRepository connectionRepository;
    private final HttpClient httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).followRedirects(HttpClient.Redirect.NORMAL).build();

    public List<RemoteTag> tags(RedemptionRemoteConnection connection) {
        JsonNode response = postJson(connection, "/api/common/profileTag/remote", Map.of(
                "openPage", false,
                "remoteOption", Map.of("select", List.of("tag_id", "name"), "filter", Map.of("tag_type", List.of("!=", 1), "status", 1)),
                "page", 1, "pageSize", 500));
        List<RemoteTag> tags = new ArrayList<>();
        JsonNode data = response.path("data");
        if (data.isArray()) for (JsonNode item : data) {
            long id = item.path("tag_id").asLong(0);
            String name = clean(item.path("name").asText(null));
            if (id > 0 && name != null) tags.add(new RemoteTag(id, name));
        }
        return tags;
    }

    public String check(RedemptionRemoteConnection connection) {
        getJson(connection, "/api/common/giftCodeConfig/index?page=1&pageSize=1&group_key=&group_desc=&valid_type=");
        return "连接正常，已验证远端兑换码配置访问权限";
    }

    public CreatedConfiguration create(RedemptionRemoteConnection connection, CreateConfigurationRequest input) {
        RemoteCreationOptions options = input.options();
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("flow_times", options.flowTimes());
        putOptional(payload, "activity_recharge", options.activityRecharge());
        putOptional(payload, "activity_recharge_count", options.activityRechargeCount());
        putOptional(payload, "activity_id", options.activityId());
        payload.put("status", "2");
        payload.put("is_need_check_uuid", flag(options.checkUuid()));
        payload.put("is_need_check_login_ip", flag(options.checkLoginIp()));
        payload.put("is_need_check_register_ip", flag(options.checkRegisterIp()));
        payload.put("user_type", input.allUsers() ? "0" : "1");
        payload.put("is_need_bind_bank_card", flag(options.requireBindBankCard()));
        payload.put("is_need_bind_phone", flag(options.requireBindPhone()));
        if (!input.allUsers()) payload.put("label_array", input.labelIds());
        payload.put("remark", input.description());
        payload.put("group_desc", input.description());
        payload.put("reward_min", input.bonusMin());
        payload.put("reward_max", input.bonusMax());
        payload.put("key_number", String.valueOf(options.keyNumber()));
        payload.put("single_user_limit", options.singleUserLimit());
        payload.put("single_key_limit", options.singleKeyLimit());
        payload.put("uuid_reward_limit", options.uuidRewardLimit());
        payload.put("login_ip_reward_limit", options.loginIpRewardLimit());
        payload.put("register_ip_reward_limit", options.registerIpRewardLimit());
        payload.put("valid_time", List.of(remoteDayStart(input.validFrom()), remoteDayEnd(input.validTo())));
        JsonNode response = postJson(connection, "/api/common/giftCodeConfig/save", payload);
        String configurationId = firstText(response, "data.id", "id");
        if (configurationId == null) throw new RemoteGiftCodeException("远端创建接口未返回兑换码配置 ID");
        // Save returns only the configuration ID. Group-key lookup is deliberately a separate call so a successful
        // remote creation is still recorded even when the list endpoint is temporarily unavailable.
        return new CreatedConfiguration(configurationId, null);
    }

    public String publishAll(RedemptionRemoteConnection connection, String publishEnvironment, boolean scheduled, java.time.LocalDateTime scheduledTime) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("env", publishEnvironment);
        payload.put("publish_type", scheduled ? "2" : "1");
        payload.put("cfg_type", 19);
        if (scheduled) payload.put("scheduled_time", scheduledTime.format(REMOTE_TIME));
        JsonNode response = postJson(connection, "/api/common/publishTask/save", payload);
        String publishTaskId = firstText(response, "data.id", "id");
        if (publishTaskId == null) throw new RemoteGiftCodeException("远端发布接口未返回发布任务 ID");
        return publishTaskId;
    }

    public void cancelScheduledPublish(RedemptionRemoteConnection connection, String publishTaskId) {
        JsonNode response = postJson(connection, "/api/common/publishTask/cancelAuto", Map.of("id", publishTaskId));
        if (response.path("data").path("ret").asInt(0) != 1) throw new RemoteGiftCodeException("远端未确认撤销定时发布");
    }

    public String downloadCode(RedemptionRemoteConnection connection, String groupKey) {
        URI uri = uri(connection.getBaseUrl(), "/api/common/giftCodeConfig/export?groupKey=" + encode(groupKey));
        byte[] bytes = send(connection, HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(30))
                .header("Content-Type", "application/json;charset=UTF-8").POST(HttpRequest.BodyPublishers.ofString("{}")), HttpResponse.BodyHandlers.ofByteArray());
        return extractCodeText(bytes);
    }

    public String findGroupKey(RedemptionRemoteConnection connection, String configurationId, String description) {
        String query = "/api/common/giftCodeConfig/index?page=1&pageSize=100&group_key=&group_desc=" + encode(description) + "&valid_type=";
        JsonNode response = getJson(connection, query);
        JsonNode items = response.path("data").path("items");
        if (!items.isArray()) return null;
        for (JsonNode item : items) {
            String id = firstText(item, "id");
            if (configurationId.equals(id)) {
                String groupKey = firstText(item, "group_key", "groupKey");
                if (groupKey != null) return groupKey;
            }
        }
        return null;
    }

    private JsonNode getJson(RedemptionRemoteConnection connection, String path) {
        URI uri = uri(connection.getBaseUrl(), path);
        String body = send(connection, HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(20)).GET(), HttpResponse.BodyHandlers.ofString());
        return parseSuccess(body);
    }

    private void putOptional(Map<String, Object> payload, String key, Object value) {
        if (value != null) payload.put(key, value);
    }

    private JsonNode postJson(RedemptionRemoteConnection connection, String path, Object payload) {
        try {
            URI uri = uri(connection.getBaseUrl(), path);
            String body = objectMapper.writeValueAsString(payload);
            String response = send(connection, HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(20))
                    .header("Content-Type", "application/json;charset=UTF-8")
                    .POST(HttpRequest.BodyPublishers.ofString(body)), HttpResponse.BodyHandlers.ofString());
            return parseSuccess(response);
        } catch (IOException exception) {
            throw new RemoteGiftCodeException("无法编码远端兑换码请求");
        }
    }

    private <T> T send(RedemptionRemoteConnection connection, HttpRequest.Builder request, HttpResponse.BodyHandler<T> handler) {
        try {
            RedemptionRemoteConnection activeConnection = connection;
            AuthenticatedResponse<T> authenticatedResponse = sendAuthenticated(activeConnection, request, handler);
            activeConnection = authenticatedResponse.connection();
            HttpResponse<T> response = authenticatedResponse.response();
            if (isSuccessful(response)) return response.body();
            if (isAuthenticationFailure(response)) {
                // The remote console can revoke a JWT before its embedded expiry. Clear the stale
                // session, log in again, and retry this exact request once so one bad token does
                // not leave an otherwise valid batch with a single failed task.
                activeConnection = clearSavedSession(activeConnection);
                authenticatedResponse = sendAuthenticated(activeConnection, request, handler);
                activeConnection = authenticatedResponse.connection();
                response = authenticatedResponse.response();
                if (isSuccessful(response)) return response.body();
                if (isAuthenticationFailure(response)) clearSavedSession(activeConnection);
            }
            throw new RemoteGiftCodeException("远端管理后台返回 HTTP " + response.statusCode());
        } catch (RemoteGiftCodeException | ApiException exception) {
            throw exception;
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new RemoteGiftCodeException("调用远端管理后台被中断");
        } catch (IOException exception) {
            throw new RemoteGiftCodeException("无法连接远端管理后台");
        }
    }

    private <T> AuthenticatedResponse<T> sendAuthenticated(RedemptionRemoteConnection connection, HttpRequest.Builder request,
                                                            HttpResponse.BodyHandler<T> handler) throws IOException, InterruptedException {
        AuthenticatedSession session = activeAccessToken(connection);
        HttpRequest built = authenticatedHeaders(request, session.connection().getBaseUrl(), session.token()).build();
        return new AuthenticatedResponse<>(session.connection(), httpClient.send(built, handler));
    }

    private boolean isSuccessful(HttpResponse<?> response) {
        return response.statusCode() >= 200 && response.statusCode() < 300;
    }

    private boolean isAuthenticationFailure(HttpResponse<?> response) {
        return response.statusCode() == 401 || response.statusCode() == 403;
    }

    private AuthenticatedSession activeAccessToken(RedemptionRemoteConnection connection) {
        if (connection.getAccessTokenCiphertext() != null && !connection.getAccessTokenCiphertext().isBlank()
                && connection.getAccessTokenExpiresAt() != null && connection.getAccessTokenExpiresAt().isAfter(Instant.now().plusSeconds(60))) {
            return new AuthenticatedSession(connection, credentialCipher.decrypt(connection.getAccessTokenCiphertext()));
        }
        return login(connection);
    }

    private AuthenticatedSession login(RedemptionRemoteConnection connection) {
        String username = clean(connection.getUsername());
        if (username == null) throw new RemoteGiftCodeException("远端账号尚未配置账号名，请编辑账号后重试");
        String password = decryptRequired(connection.getPasswordCiphertext(), "登录密码");
        String totpSecret = decryptRequired(connection.getTotpSecretCiphertext(), "TOTP 秘钥");
        try {
            URI loginUrl = uri(connection.getBaseUrl(), "/api/system/login");
            String payload = objectMapper.writeValueAsString(Map.of("username", username, "password", password, "code", RemoteTotp.generate(totpSecret)));
            HttpRequest.Builder request = HttpRequest.newBuilder(loginUrl).timeout(Duration.ofSeconds(20))
                    .header("Content-Type", "application/json;charset=UTF-8")
                    .header("Authorization", "Bearer null")
                    .POST(HttpRequest.BodyPublishers.ofString(payload));
            HttpResponse<String> response = httpClient.send(loginHeaders(request, connection.getBaseUrl()).build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new RemoteGiftCodeException("远端登录接口返回 HTTP " + response.statusCode());
            }
            JsonNode parsed = parseSuccess(response.body());
            String token = findAccessToken(parsed);
            if (token == null) throw new RemoteGiftCodeException("远端登录接口未返回访问令牌");
            RedemptionRemoteConnection saved = saveSession(connection, credentialCipher.encrypt(token),
                    jwtExpiry(token).orElseGet(() -> Instant.now().plus(Duration.ofMinutes(20))), Instant.now(), null);
            return new AuthenticatedSession(saved, token);
        } catch (RemoteGiftCodeException | ApiException exception) {
            throw new RemoteGiftCodeException("远端登录失败：" + exception.getMessage());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new RemoteGiftCodeException("远端登录被中断");
        } catch (IOException exception) {
            throw new RemoteGiftCodeException("无法连接远端管理后台登录接口");
        }
    }

    private HttpRequest.Builder authenticatedHeaders(HttpRequest.Builder request, String baseUrl, String token) {
        return loginHeaders(request, baseUrl).setHeader("Authorization", "Bearer " + token);
    }

    private HttpRequest.Builder loginHeaders(HttpRequest.Builder request, String baseUrl) {
        String origin = origin(baseUrl);
        return request.setHeader("Accept", "application/json, text/plain, */*")
                .setHeader("Accept-Language", "zh_CN")
                .setHeader("Origin", origin)
                .setHeader("Referer", origin + "/")
                .setHeader("User-Agent", "Mozilla/5.0 (compatible; RajAdsManage/1.0)");
    }

    private String decryptRequired(String ciphertext, String field) {
        if (ciphertext == null || ciphertext.isBlank()) throw new RemoteGiftCodeException("远端账号尚未配置" + field + "，请编辑账号后重试");
        return credentialCipher.decrypt(ciphertext);
    }

    private RedemptionRemoteConnection clearSavedSession(RedemptionRemoteConnection connection) {
        return saveSession(connection, null, null, null, null);
    }

    /**
     * Remote calls receive detached connections from prior transactions. Persist session fields against a freshly
     * loaded row and return that row so a 401 cleanup never writes the pre-login row version.
     */
    private RedemptionRemoteConnection saveSession(RedemptionRemoteConnection connection, String tokenCiphertext,
                                                    Instant tokenExpiresAt, Instant loggedInAt, String lastError) {
        if (connection.getId() == null) {
            connection.setAccessTokenCiphertext(tokenCiphertext);
            connection.setAccessTokenExpiresAt(tokenExpiresAt);
            if (loggedInAt != null) connection.setLastLoggedInAt(loggedInAt);
            connection.setLastError(lastError);
            return connection;
        }
        for (int attempt = 0; attempt < 2; attempt++) {
            RedemptionRemoteConnection current = connectionRepository.findById(connection.getId())
                    .orElseThrow(() -> ApiException.notFound("远端账号"));
            current.setAccessTokenCiphertext(tokenCiphertext);
            current.setAccessTokenExpiresAt(tokenExpiresAt);
            if (loggedInAt != null) current.setLastLoggedInAt(loggedInAt);
            current.setLastError(lastError);
            try {
                return connectionRepository.saveAndFlush(current);
            } catch (ObjectOptimisticLockingFailureException exception) {
                if (attempt == 1) throw exception;
            }
        }
        throw new IllegalStateException("无法保存远端账号会话");
    }

    private String origin(String baseUrl) {
        URI parsed = uri(baseUrl, "");
        return parsed.getScheme() + "://" + parsed.getAuthority();
    }

    private String findAccessToken(JsonNode node) {
        if (node == null || node.isNull()) return null;
        if (node.isObject()) {
            for (String name : List.of("token", "jwt", "access_token", "accessToken")) {
                String value = clean(node.path(name).asText(null));
                if (value != null) return value;
            }
            Iterator<JsonNode> children = node.elements();
            while (children.hasNext()) {
                String value = findAccessToken(children.next());
                if (value != null) return value;
            }
        } else if (node.isArray()) {
            for (JsonNode item : node) {
                String value = findAccessToken(item);
                if (value != null) return value;
            }
        }
        return null;
    }

    private Optional<Instant> jwtExpiry(String token) {
        try {
            String[] parts = token.split("\\.");
            if (parts.length < 2) return Optional.empty();
            JsonNode claims = objectMapper.readTree(Base64.getUrlDecoder().decode(parts[1]));
            long expiresAt = claims.path("exp").asLong(0);
            return expiresAt > 0 ? Optional.of(Instant.ofEpochSecond(expiresAt)) : Optional.empty();
        } catch (RuntimeException | IOException ignored) {
            return Optional.empty();
        }
    }

    private JsonNode parseSuccess(String responseBody) {
        try {
            JsonNode response = objectMapper.readTree(responseBody);
            if (!response.path("success").asBoolean(false) && response.path("code").asInt(0) != 200) {
                throw new RemoteGiftCodeException(clean(response.path("message").asText(null)) == null ? "远端管理后台请求失败" : clean(response.path("message").asText(null)));
            }
            return response;
        } catch (RemoteGiftCodeException exception) {
            throw exception;
        } catch (IOException exception) {
            throw new RemoteGiftCodeException("远端管理后台返回了无法识别的数据");
        }
    }

    private String extractCodeText(byte[] bytes) {
        try (Workbook workbook = WorkbookFactory.create(new ByteArrayInputStream(bytes))) {
            var sheet = workbook.getNumberOfSheets() == 0 ? null : workbook.getSheetAt(0);
            if (sheet == null) throw new RemoteGiftCodeException("下载的远端兑换码文件为空");
            DataFormatter formatter = new DataFormatter();
            Row header = sheet.getRow(sheet.getFirstRowNum());
            int codeColumn = -1;
            if (header != null) for (Cell cell : header) {
                if ("兑换码号码".equals(clean(formatter.formatCellValue(cell)))) { codeColumn = cell.getColumnIndex(); break; }
            }
            if (codeColumn < 0) throw new RemoteGiftCodeException("下载文件中找不到“兑换码号码”列");
            Set<String> codes = new LinkedHashSet<>();
            for (int index = header.getRowNum() + 1; index <= sheet.getLastRowNum(); index++) {
                Row row = sheet.getRow(index);
                if (row == null) continue;
                String code = clean(formatter.formatCellValue(row.getCell(codeColumn)));
                if (code != null && !codes.add(code)) throw new RemoteGiftCodeException("下载文件包含重复的兑换码");
            }
            if (codes.isEmpty() || codes.size() > 1000) throw new RemoteGiftCodeException("下载文件的兑换码数量须为 1–1000");
            return String.join("\n", codes);
        } catch (RemoteGiftCodeException exception) {
            throw exception;
        } catch (IOException exception) {
            throw new RemoteGiftCodeException("无法解析远端下载的兑换码 Excel");
        }
    }

    private URI uri(String baseUrl, String path) {
        try {
            String base = clean(baseUrl);
            if (base == null) throw new IllegalArgumentException();
            base = base.replaceAll("/+$", "");
            if (base.endsWith("/api")) base = base.substring(0, base.length() - 4);
            URI parsed = URI.create(base);
            if (!("https".equalsIgnoreCase(parsed.getScheme()) || "http".equalsIgnoreCase(parsed.getScheme())) || parsed.getHost() == null || parsed.getQuery() != null || parsed.getFragment() != null) throw new IllegalArgumentException();
            return URI.create(base + path);
        } catch (IllegalArgumentException exception) {
            throw new RemoteGiftCodeException("远端连接的 Base URL 无效");
        }
    }

    private String remoteDayStart(LocalDate date) { return date.atStartOfDay().format(REMOTE_TIME); }
    private String remoteDayEnd(LocalDate date) { return date.atTime(23, 59, 59).format(REMOTE_TIME); }
    private String flag(boolean value) { return value ? "1" : "0"; }
    private String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }
    private String firstText(JsonNode source, String... paths) {
        for (String path : paths) {
            JsonNode value = source;
            for (String segment : path.split("\\.")) value = value == null ? null : value.path(segment);
            String text = value == null ? null : clean(value.asText(null));
            if (text != null) return text;
        }
        return null;
    }
    private String clean(String value) { return value == null || value.isBlank() ? null : value.trim(); }

    private record AuthenticatedSession(RedemptionRemoteConnection connection, String token) { }
    private record AuthenticatedResponse<T>(RedemptionRemoteConnection connection, HttpResponse<T> response) { }
    public record RemoteTag(long id, String name) { }
    public record CreateConfigurationRequest(String description, List<Long> labelIds, boolean allUsers, BigDecimal bonusMin, BigDecimal bonusMax,
                                             LocalDate claimDate, LocalDate validFrom, LocalDate validTo, RemoteCreationOptions options) { }
    public record CreatedConfiguration(String configurationId, String groupKey) { }
    public static final class RemoteGiftCodeException extends RuntimeException { public RemoteGiftCodeException(String message) { super(message); } }
}
