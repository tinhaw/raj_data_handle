package com.rajads.erp.identity;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;

import java.time.Instant;
import java.util.List;
import java.util.Set;

public final class IdentityDtos {
    private IdentityDtos() {
    }

    public record LoginRequest(@NotBlank String username, @NotBlank String password) {
    }

    public record ChangePasswordRequest(@NotBlank String currentPassword,
                                        @NotBlank @Size(min = 8, max = 100) String newPassword) {
    }

    public record UserRequest(@NotBlank @Size(max = 80) String username,
                              @Size(min = 8, max = 100) String password,
                              @NotBlank @Size(max = 120) String displayName,
                              Boolean enabled,
                              Set<String> roleCodes,
                              Boolean allOperators,
                              Set<Long> operatorIds) {
    }

    public record UserPatchRequest(String displayName, Boolean enabled, Long rowVersion) {
    }

    public record AssignRolesRequest(@NotEmpty Set<String> roleCodes) {
    }

    public record AssignScopesRequest(Boolean allOperators, Set<Long> operatorIds) {
    }

    public record RoleResponse(Long id, String code, String name, String description, Set<String> permissions) {
    }

    public record UserResponse(Long id, String username, String displayName, boolean enabled,
                               boolean mustChangePassword, Set<String> roles, Set<String> permissions,
                               boolean allOperators, Set<Long> operatorIds, Instant createdAt, Long rowVersion) {
    }

    public record LoginResponse(UserResponse user) {
    }

    public record ListResponse<T>(List<T> items) {
    }
}
