package com.rajads.erp.identity;

import com.rajads.erp.audit.AuditService;
import com.rajads.erp.shared.ApiException;
import jakarta.transaction.Transactional;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "true")
public class IdentityService implements UserDetailsService {
    private final AppUserRepository userRepository;
    private final RoleRepository roleRepository;
    private final UserOperatorScopeRepository scopeRepository;
    private final PasswordEncoder passwordEncoder;
    private final AuditService auditService;

    @Override
    @Transactional
    public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        AppUser user = userRepository.findByUsernameIgnoreCase(username)
                .orElseThrow(() -> new UsernameNotFoundException("用户名或密码不正确"));
        return toAuthUser(user);
    }

    /** Used by the session filter to apply user disablement and role changes without requiring a new login. */
    @Transactional
    public Optional<AuthUser> findEnabledAuthUser(Long id) {
        return userRepository.findById(id).filter(AppUser::isEnabled).map(this::toAuthUser);
    }

    @Transactional
    public IdentityDtos.UserResponse me(AuthUser authUser) {
        return response(requireUser(authUser.id()));
    }

    @Transactional
    public List<IdentityDtos.UserResponse> listUsers() {
        return userRepository.findAll().stream().map(this::response).toList();
    }

    @Transactional
    public IdentityDtos.UserResponse create(IdentityDtos.UserRequest request) {
        if (userRepository.existsByUsernameIgnoreCase(request.username())) {
            throw ApiException.conflict("USERNAME_EXISTS", "用户名已存在");
        }
        if (request.password() == null || request.password().length() < 8) {
            throw ApiException.badRequest("INVALID_PASSWORD", "初始密码至少 8 位");
        }
        AppUser user = new AppUser();
        user.setUsername(request.username().trim());
        user.setPasswordHash(passwordEncoder.encode(request.password()));
        user.setDisplayName(request.displayName().trim());
        user.setEnabled(request.enabled() == null || request.enabled());
        user.setMustChangePassword(true);
        applyRoles(user, request.roleCodes() == null || request.roleCodes().isEmpty() ? Set.of("DATA_ENTRY") : request.roleCodes());
        user = userRepository.save(user);
        replaceScopes(user.getId(), Boolean.TRUE.equals(request.allOperators()), request.operatorIds());
        auditService.record("USER_CREATED", "USER", user.getId().toString(), null, null, response(user));
        return response(user);
    }

    @Transactional
    public IdentityDtos.UserResponse patch(Long id, IdentityDtos.UserPatchRequest request) {
        AppUser user = requireUser(id);
        if (request.rowVersion() != null && !Objects.equals(request.rowVersion(), user.getRowVersion())) {
            throw ApiException.conflict("USER_VERSION_CONFLICT", "用户已被其他人修改");
        }
        if (request.displayName() != null && !request.displayName().isBlank()) {
            user.setDisplayName(request.displayName().trim());
        }
        if (request.enabled() != null) {
            user.setEnabled(request.enabled());
        }
        userRepository.save(user);
        auditService.record("USER_UPDATED", "USER", id.toString(), null, null, response(user));
        return response(user);
    }

    @Transactional
    public IdentityDtos.UserResponse assignRoles(Long id, Set<String> roleCodes) {
        AppUser user = requireUser(id);
        applyRoles(user, roleCodes);
        userRepository.save(user);
        auditService.record("USER_ROLES_UPDATED", "USER", id.toString(), null, null, response(user));
        return response(user);
    }

    @Transactional
    public IdentityDtos.UserResponse assignScopes(Long id, boolean allOperators, Set<Long> operatorIds) {
        requireUser(id);
        replaceScopes(id, allOperators, operatorIds);
        IdentityDtos.UserResponse response = response(requireUser(id));
        auditService.record("USER_SCOPES_UPDATED", "USER", id.toString(), null, null, response);
        return response;
    }

    @Transactional
    public void changePassword(AuthUser principal, IdentityDtos.ChangePasswordRequest request) {
        AppUser user = requireUser(principal.id());
        if (!passwordEncoder.matches(request.currentPassword(), user.getPasswordHash())) {
            throw ApiException.badRequest("CURRENT_PASSWORD_INVALID", "当前密码不正确");
        }
        user.setPasswordHash(passwordEncoder.encode(request.newPassword()));
        user.setMustChangePassword(false);
        userRepository.save(user);
        auditService.record("PASSWORD_CHANGED", "USER", user.getId().toString(), null, null, Map.of("self", true));
    }

    @Transactional
    public List<IdentityDtos.RoleResponse> listRoles() {
        return roleRepository.findAll().stream().map(role -> new IdentityDtos.RoleResponse(
                role.getId(), role.getCode(), role.getName(), role.getDescription(),
                role.getPermissions().stream().map(Permission::getCode).collect(Collectors.toCollection(TreeSet::new))
        )).toList();
    }

    public AuthUser toAuthUser(AppUser user) {
        Set<String> roles = user.getRoles().stream().map(Role::getCode)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> permissions = user.getRoles().stream().flatMap(role -> role.getPermissions().stream())
                .map(Permission::getCode).collect(Collectors.toCollection(LinkedHashSet::new));
        return new AuthUser(user.getId(), user.getUsername(), user.getPasswordHash(), user.getDisplayName(),
                user.isEnabled(), user.isMustChangePassword(), roles, permissions);
    }

    private AppUser requireUser(Long id) {
        return userRepository.findById(id).orElseThrow(() -> ApiException.notFound("用户"));
    }

    private void applyRoles(AppUser user, Set<String> codes) {
        List<Role> roles = roleRepository.findByCodeIn(codes);
        if (roles.size() != codes.size()) {
            throw ApiException.badRequest("ROLE_NOT_FOUND", "存在未知角色");
        }
        user.setRoles(new LinkedHashSet<>(roles));
    }

    private void replaceScopes(Long userId, boolean allOperators, Set<Long> operatorIds) {
        scopeRepository.deleteByUserId(userId);
        if (allOperators) {
            scopeRepository.save(new UserOperatorScope(userId, null, true));
            return;
        }
        if (operatorIds != null) {
            operatorIds.forEach(operatorId -> scopeRepository.save(new UserOperatorScope(userId, operatorId, false)));
        }
    }

    private IdentityDtos.UserResponse response(AppUser user) {
        List<UserOperatorScope> scopes = scopeRepository.findByUserId(user.getId());
        boolean all = scopes.stream().anyMatch(UserOperatorScope::isAllOperators) || user.getRoles().stream()
                .anyMatch(role -> "SUPER_ADMIN".equals(role.getCode()));
        Set<Long> ids = scopes.stream().map(UserOperatorScope::getOperatorId).filter(Objects::nonNull)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        AuthUser auth = toAuthUser(user);
        return new IdentityDtos.UserResponse(user.getId(), user.getUsername(), user.getDisplayName(), user.isEnabled(),
                user.isMustChangePassword(), auth.roles(), auth.permissions(), all, ids, user.getCreatedAt(), user.getRowVersion());
    }
}
