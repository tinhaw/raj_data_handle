package com.rajads.erp.shared;

import jakarta.persistence.OptimisticLockException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import static org.assertj.core.api.Assertions.assertThat;

class GlobalExceptionHandlerTest {
    @Test
    void optimisticLockIsReportedAsConflict() {
        var response = new GlobalExceptionHandler().handleOptimisticLock(new OptimisticLockException(), new MockHttpServletRequest());

        assertThat(response.getStatusCode().value()).isEqualTo(409);
        assertThat(response.getBody().code()).isEqualTo("BALANCE_VERSION_CONFLICT");
    }
}
