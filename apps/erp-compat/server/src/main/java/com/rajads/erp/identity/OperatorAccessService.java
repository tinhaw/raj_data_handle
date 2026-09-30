package com.rajads.erp.identity;

import com.rajads.erp.shared.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class OperatorAccessService {
    private final CurrentUser currentUser;
    private final UserOperatorScopeRepository scopeRepository;

    @Transactional(readOnly = true)
    public boolean hasAllOperators() {
        AuthUser user = currentUser.require();
        if (user.roles().contains("COMPATIBILITY_BRIDGED")) {
            return CompatibilityPrincipalDetails.current().allOperators();
        }
        return user.roles().contains("SUPER_ADMIN") || scopeRepository.findByUserId(user.id()).stream()
                .anyMatch(UserOperatorScope::isAllOperators);
    }

    @Transactional(readOnly = true)
    public Set<Long> accessibleOperatorIds() {
        AuthUser user = currentUser.require();
        if (user.roles().contains("COMPATIBILITY_BRIDGED")) {
            return new LinkedHashSet<>(CompatibilityPrincipalDetails.current().operatorIds());
        }
        if (user.roles().contains("SUPER_ADMIN")) return Set.of();
        return scopeRepository.findByUserId(user.id()).stream().filter(scope -> !scope.isAllOperators())
                .map(UserOperatorScope::getOperatorId).filter(java.util.Objects::nonNull)
                .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));
    }

    public void requireAccess(Long operatorId) {
        if (hasAllOperators()) return;
        if (!accessibleOperatorIds().contains(operatorId)) {
            throw ApiException.forbidden("没有该投放公司的数据权限");
        }
    }

    public void requireAccess(Collection<Long> operatorIds) {
        if (operatorIds == null || operatorIds.isEmpty() || hasAllOperators()) return;
        Set<Long> allowed = accessibleOperatorIds();
        if (!allowed.containsAll(operatorIds)) {
            throw ApiException.forbidden("包含未授权的投放公司");
        }
    }
}
