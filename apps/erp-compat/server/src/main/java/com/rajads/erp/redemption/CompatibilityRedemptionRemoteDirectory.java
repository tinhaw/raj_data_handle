package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.Collection;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Optional;

/** Unified SourceConfig + RemoteAccount adapter for the imported ERP service. */
@Component
@Primary
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilityRedemptionRemoteDirectory implements RedemptionRemoteDirectory {
    private final CompatibilityRemoteRegistryClient client;
    private final String sessionCookieName;

    public CompatibilityRedemptionRemoteDirectory(
            CompatibilityRemoteRegistryClient client,
            @Value("${erp.compatibility.session-cookie-name:raj_session}") String sessionCookieName) {
        this.client = client;
        this.sessionCookieName = sessionCookieName;
    }

    @Override
    public Account requireEnabled(Long id) {
        CompatibilityRemoteRegistry.Connection connection = connection(id)
                .orElseThrow(() -> ApiException.notFound("远端账号"));
        requireCreateCapability(connection);
        if (!connection.enabled()) {
            throw ApiException.conflict("REMOTE_CONNECTION_DISABLED", "所选远端账号已停用，请选择其他可用账号");
        }
        if (!connection.marketEnabled()) {
            throw ApiException.conflict("REMOTE_MARKET_DISABLED", "所选盘口已停用，请选择其他可用盘口账号");
        }
        return account(connection);
    }

    @Override
    public Account selectEnabledForMarket(Long marketId) {
        CompatibilityRemoteRegistry registry = registry();
        CompatibilityRemoteRegistry.Market market = registry.markets().stream()
                .filter(item -> item.id().equals(marketId))
                .findFirst()
                .orElseThrow(() -> ApiException.notFound("远端盘口"));
        if (!market.enabled()) {
            throw ApiException.conflict("REMOTE_MARKET_DISABLED", "所选盘口已停用，请选择已启用盘口");
        }
        return registry.connections().stream()
                .filter(item -> item.marketId().equals(marketId))
                .filter(CompatibilityRemoteRegistry.Connection::enabled)
                .filter(item -> capability(item, "ERP_REDEMPTION_CREATE"))
                .sorted(Comparator.comparing(item -> Optional.ofNullable(item.username()).orElse("")))
                .findFirst()
                .map(this::account)
                .orElseThrow(() -> ApiException.conflict(
                        "REMOTE_MARKET_NO_AVAILABLE_CONNECTION",
                        "所选盘口暂无已授权的远端账号，请前往“远端账号与盘口”配置账号能力"
                ));
    }

    @Override
    public void requireCurrentTags(Long id, Collection<Long> requestedTagIds) {
        if (requestedTagIds == null || requestedTagIds.isEmpty()) return;
        CompatibilityRemoteRegistry.Connection connection = connection(id)
                .orElseThrow(() -> ApiException.notFound("远端账号"));
        HashSet<Long> available = new HashSet<>(connection.tagIds() == null
                ? java.util.List.of() : connection.tagIds());
        java.util.List<Long> missing = requestedTagIds.stream()
                .filter(value -> value == null || !available.contains(value))
                .distinct()
                .sorted(Comparator.nullsFirst(Comparator.naturalOrder()))
                .toList();
        if (!missing.isEmpty()) {
            throw ApiException.conflict(
                    "REMOTE_TAG_NOT_AVAILABLE",
                    "所选盘口的统一标签快照不存在标签 ID：" + missing + "；请先在主系统核对标签快照"
            );
        }
    }

    @Override
    public Optional<Account> find(Long id) {
        return connection(id).map(this::account);
    }

    private Optional<CompatibilityRemoteRegistry.Connection> connection(Long id) {
        if (id == null) return Optional.empty();
        return registry().connections().stream().filter(item -> item.id().equals(id)).findFirst();
    }

    private CompatibilityRemoteRegistry registry() {
        return client.get(sessionCookieName, sessionCookie());
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

    private void requireCreateCapability(CompatibilityRemoteRegistry.Connection connection) {
        if (!capability(connection, "ERP_REDEMPTION_CREATE")) {
            throw ApiException.forbidden("远端账号未获得 ERP_REDEMPTION_CREATE 能力授权");
        }
    }

    private boolean capability(CompatibilityRemoteRegistry.Connection connection, String name) {
        return connection.capabilities() != null && Boolean.TRUE.equals(connection.capabilities().get(name));
    }

    private Account account(CompatibilityRemoteRegistry.Connection connection) {
        return new Account(
                connection.id(),
                connection.username(),
                connection.marketId(),
                connection.marketCode(),
                connection.marketName(),
                connection.enabled(),
                connection.marketEnabled()
        );
    }
}
