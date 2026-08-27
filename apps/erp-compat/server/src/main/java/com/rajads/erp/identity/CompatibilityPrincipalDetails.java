package com.rajads.erp.identity;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Set;

public final class CompatibilityPrincipalDetails {
    private CompatibilityPrincipalDetails() {
    }

    public static CompatibilityAuthenticationDetails current() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.getDetails() instanceof CompatibilityAuthenticationDetails details) {
            return details;
        }
        return new CompatibilityAuthenticationDetails(false, Set.of());
    }
}
