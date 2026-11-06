package com.rajads.erp.identity;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** Minimal old frontend contract backed by the current application session. */
@RestController
@RequestMapping("/api/v1/auth")
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class CompatibilityAuthController {
    private final CurrentUser currentUser;

    public CompatibilityAuthController(CurrentUser currentUser) {
        this.currentUser = currentUser;
    }

    @GetMapping("/me")
    public IdentityDtos.UserResponse me() {
        AuthUser user = currentUser.require();
        CompatibilityAuthenticationDetails details = CompatibilityPrincipalDetails.current();
        return new IdentityDtos.UserResponse(user.id(), user.username(), user.displayName(), true, false,
                user.roles(), user.permissions(), details.allOperators(), details.operatorIds(), null, 0L);
    }

    @GetMapping("/csrf")
    public Map<String, String> csrfCompatibilityNoop() {
        return Map.of();
    }
}
