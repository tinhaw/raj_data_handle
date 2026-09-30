package com.rajads.erp.audit;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.identity.AuthUser;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.shared.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class AuditService {
    private final AuditLogRepository repository;
    private final ObjectMapper objectMapper;
    private final CurrentUser currentUser;
    private final HttpServletRequest request;

    @Transactional(propagation = Propagation.REQUIRED)
    public void record(String action, String entityType, String entityId, Long operatorId, Object before, Object after) {
        AuditLog log = new AuditLog();
        log.setAction(action);
        log.setEntityType(entityType);
        log.setEntityId(entityId);
        log.setOperatorId(operatorId);
        log.setBeforeJson(toJson(before));
        log.setAfterJson(toJson(after));
        log.setRequestId((String) request.getAttribute(RequestIdFilter.REQUEST_ID_ATTRIBUTE));
        log.setIpAddress(request.getRemoteAddr());
        try {
            AuthUser user = currentUser.require();
            log.setActorUserId(user.id());
        } catch (RuntimeException ignored) {
            // Bootstrap and failed-login audit entries intentionally have no actor.
        }
        repository.save(log);
    }

    private String toJson(Object value) {
        if (value == null) return null;
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ignored) {
            return "{\"serialization\":\"unavailable\"}";
        }
    }
}
