package com.rajads.erp.identity;

import com.rajads.erp.audit.AuditService;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "true")
public class AuthController {
    private final AuthenticationManager authenticationManager;
    private final IdentityService identityService;
    private final CurrentUser currentUser;
    private final AuditService auditService;

    @PostMapping("/login")
    @Operation(summary = "用户名密码登录")
    public IdentityDtos.LoginResponse login(@Valid @RequestBody IdentityDtos.LoginRequest request, HttpServletRequest servletRequest) {
        Authentication authentication = authenticationManager.authenticate(
                UsernamePasswordAuthenticationToken.unauthenticated(request.username(), request.password()));
        SecurityContext context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(authentication);
        SecurityContextHolder.setContext(context);
        HttpSession session = servletRequest.getSession(true);
        session.setAttribute(HttpSessionSecurityContextRepository.SPRING_SECURITY_CONTEXT_KEY, context);
        AuthUser user = (AuthUser) authentication.getPrincipal();
        auditService.record("LOGIN", "USER", user.id().toString(), null, null, java.util.Map.of("username", user.username()));
        return new IdentityDtos.LoginResponse(identityService.me(user));
    }

    @PostMapping("/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void logout(HttpServletRequest request) {
        HttpSession session = request.getSession(false);
        if (session != null) session.invalidate();
        SecurityContextHolder.clearContext();
    }

    @GetMapping("/me")
    public IdentityDtos.UserResponse me() {
        return identityService.me(currentUser.require());
    }

    @GetMapping("/csrf")
    public java.util.Map<String, String> csrf(CsrfToken csrfToken) {
        return java.util.Map.of("token", csrfToken.getToken(), "headerName", csrfToken.getHeaderName(), "parameterName", csrfToken.getParameterName());
    }

    @PostMapping("/password/change")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void changePassword(@Valid @RequestBody IdentityDtos.ChangePasswordRequest request) {
        identityService.changePassword(currentUser.require(), request);
    }
}
