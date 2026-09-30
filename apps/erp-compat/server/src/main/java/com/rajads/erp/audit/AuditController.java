package com.rajads.erp.audit;

import io.swagger.v3.oas.annotations.Operation;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.identity.OperatorAccessService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Sort;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.List;
import java.util.Set;

@RestController
@RequestMapping("/api/v1/audit-logs")
@RequiredArgsConstructor
public class AuditController {
    private final AuditLogRepository repository;
    private final OperatorAccessService operatorAccessService;
    private final CurrentUser currentUser;

    @GetMapping
    @PreAuthorize("hasAuthority('AUDIT_VIEW')")
    @Operation(summary = "查询审计日志")
    public List<AuditLog> list(@RequestParam(required = false) String action,
                               @RequestParam(required = false) Long operatorId,
                               @RequestParam(required = false) Instant from,
                               @RequestParam(required = false) Instant to) {
        if (operatorId != null) operatorAccessService.requireAccess(operatorId);
        boolean allOperators = operatorAccessService.hasAllOperators();
        Set<Long> allowedOperatorIds = allOperators ? Set.of() : operatorAccessService.accessibleOperatorIds();
        Long currentUserId = currentUser.require().id();
        return repository.findAll((root, query, builder) -> {
            var predicate = builder.conjunction();
            if (action != null && !action.isBlank()) predicate = builder.and(predicate, builder.equal(root.get("action"), action));
            if (operatorId != null) predicate = builder.and(predicate, builder.equal(root.get("operatorId"), operatorId));
            if (from != null) predicate = builder.and(predicate, builder.greaterThanOrEqualTo(root.get("createdAt"), from));
            if (to != null) predicate = builder.and(predicate, builder.lessThanOrEqualTo(root.get("createdAt"), to));
            if (!allOperators) {
                var scopedBusinessLogs = allowedOperatorIds.isEmpty() ? builder.disjunction()
                        : root.get("operatorId").in(allowedOperatorIds);
                var ownGlobalLogs = builder.and(builder.isNull(root.get("operatorId")), builder.equal(root.get("actorUserId"), currentUserId));
                predicate = builder.and(predicate, builder.or(scopedBusinessLogs, ownGlobalLogs));
            }
            return predicate;
        }, Sort.by(Sort.Direction.DESC, "createdAt"));
    }
}
