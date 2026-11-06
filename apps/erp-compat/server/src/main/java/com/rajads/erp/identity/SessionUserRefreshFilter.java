package com.rajads.erp.identity;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/** Reloads the session principal so disabling a user or changing roles takes effect on the next request. */
@RequiredArgsConstructor
public class SessionUserRefreshFilter extends OncePerRequestFilter {
    private final IdentityService identityService;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.isAuthenticated() && authentication.getPrincipal() instanceof AuthUser sessionUser) {
            identityService.findEnabledAuthUser(sessionUser.id()).ifPresentOrElse(freshUser -> {
                UsernamePasswordAuthenticationToken refreshed = UsernamePasswordAuthenticationToken.authenticated(
                        freshUser, null, freshUser.getAuthorities());
                refreshed.setDetails(authentication.getDetails());
                SecurityContextHolder.getContext().setAuthentication(refreshed);
            }, () -> {
                SecurityContextHolder.clearContext();
                HttpSession session = request.getSession(false);
                if (session != null) session.invalidate();
            });
        }
        filterChain.doFilter(request, response);
    }
}
