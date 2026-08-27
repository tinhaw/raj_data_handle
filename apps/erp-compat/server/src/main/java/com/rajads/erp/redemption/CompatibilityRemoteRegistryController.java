package com.rajads.erp.redemption;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;

import java.util.List;

/** Old read contracts backed exclusively by SourceConfig + RemoteAccount. */
@RestController
@RequestMapping("/api/v1")
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilityRemoteRegistryController {
    private final CompatibilityRemoteRegistryClient client;
    private final String sessionCookieName;

    public CompatibilityRemoteRegistryController(
            CompatibilityRemoteRegistryClient client,
            @Value("${erp.compatibility.session-cookie-name:raj_session}") String sessionCookieName) {
        this.client = client;
        this.sessionCookieName = sessionCookieName;
    }

    @GetMapping("/redemption-remote-markets")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<CompatibilityRemoteRegistry.Market> markets(HttpServletRequest request) {
        return client.get(sessionCookieName, session(request)).markets();
    }

    @GetMapping("/redemption-remote-connections")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public List<CompatibilityRemoteRegistry.Connection> connections(HttpServletRequest request) {
        return client.get(sessionCookieName, session(request)).connections();
    }

    private String session(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) return null;
        for (Cookie cookie : cookies) if (sessionCookieName.equals(cookie.getName())) return cookie.getValue();
        return null;
    }
}
