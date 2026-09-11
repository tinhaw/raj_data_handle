package com.rajads.erp.identity;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.shared.ApiError;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.Set;

/** Creates a Spring principal only after the main application validates raj_session. */
@Component
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilityIdentityFilter extends OncePerRequestFilter {
    private final CompatibilityIdentityClient identityClient;
    private final ObjectMapper objectMapper;
    private final String sessionCookieName;

    public CompatibilityIdentityFilter(
            CompatibilityIdentityClient identityClient,
            ObjectMapper objectMapper,
            @Value("${erp.compatibility.session-cookie-name:raj_session}") String sessionCookieName) {
        this.identityClient = identityClient;
        this.objectMapper = objectMapper;
        this.sessionCookieName = sessionCookieName;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String session = cookie(request.getCookies(), sessionCookieName);
        try {
            identityClient.resolve(sessionCookieName, session).ifPresent(identity -> {
                Set<String> roles = new LinkedHashSet<>(identity.roleGrants());
                roles.add("COMPATIBILITY_BRIDGED");
                if (identity.allOperators()) roles.add("SUPER_ADMIN");
                AuthUser principal = new AuthUser(identity.userId(), identity.username(), "", identity.displayName(),
                        true, false, roles, CompatibilityAuthorityMapper.map(identity.effectivePermissions()));
                UsernamePasswordAuthenticationToken authentication = UsernamePasswordAuthenticationToken.authenticated(
                        principal, null, principal.getAuthorities());
                authentication.setDetails(new CompatibilityAuthenticationDetails(
                        identity.allOperators(), identity.operatorIds()));
                SecurityContextHolder.getContext().setAuthentication(authentication);
            });
            filterChain.doFilter(request, response);
        } catch (CompatibilityIdentityUnavailableException exception) {
            SecurityContextHolder.clearContext();
            response.setStatus(HttpServletResponse.SC_SERVICE_UNAVAILABLE);
            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            objectMapper.writeValue(response.getOutputStream(), new ApiError(
                    "IDENTITY_SERVICE_UNAVAILABLE", exception.getMessage(), null, Instant.now(), java.util.Map.of()));
        }
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return "OPTIONS".equals(request.getMethod()) || path.startsWith("/actuator/")
                || path.startsWith("/api-docs") || path.startsWith("/swagger-ui");
    }

    private String cookie(Cookie[] cookies, String name) {
        if (cookies == null) return null;
        for (Cookie cookie : cookies) if (name.equals(cookie.getName())) return cookie.getValue();
        return null;
    }
}
