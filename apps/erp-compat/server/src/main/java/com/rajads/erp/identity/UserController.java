package com.rajads.erp.identity;

import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "true")
public class UserController {
    private final IdentityService identityService;

    @GetMapping("/users")
    @PreAuthorize("hasAuthority('USER_MANAGE')")
    public List<IdentityDtos.UserResponse> list() { return identityService.listUsers(); }

    @PostMapping("/users")
    @PreAuthorize("hasAuthority('USER_MANAGE')")
    public IdentityDtos.UserResponse create(@Valid @RequestBody IdentityDtos.UserRequest request) { return identityService.create(request); }

    @PatchMapping("/users/{id}")
    @PreAuthorize("hasAuthority('USER_MANAGE')")
    public IdentityDtos.UserResponse patch(@PathVariable Long id, @RequestBody IdentityDtos.UserPatchRequest request) { return identityService.patch(id, request); }

    @PutMapping("/users/{id}/roles")
    @PreAuthorize("hasAuthority('USER_MANAGE')")
    public IdentityDtos.UserResponse roles(@PathVariable Long id, @Valid @RequestBody IdentityDtos.AssignRolesRequest request) {
        return identityService.assignRoles(id, request.roleCodes());
    }

    @PutMapping("/users/{id}/operator-scopes")
    @PreAuthorize("hasAuthority('USER_MANAGE')")
    public IdentityDtos.UserResponse scopes(@PathVariable Long id, @RequestBody IdentityDtos.AssignScopesRequest request) {
        return identityService.assignScopes(id, Boolean.TRUE.equals(request.allOperators()), request.operatorIds());
    }

    @GetMapping("/roles")
    @PreAuthorize("isAuthenticated()")
    public List<IdentityDtos.RoleResponse> roles() { return identityService.listRoles(); }
}
