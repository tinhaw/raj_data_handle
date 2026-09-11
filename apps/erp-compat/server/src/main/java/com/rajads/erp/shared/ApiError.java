package com.rajads.erp.shared;

import java.time.Instant;
import java.util.Map;

public record ApiError(
        String code,
        String message,
        String requestId,
        Instant timestamp,
        Map<String, Object> details
) {
}
