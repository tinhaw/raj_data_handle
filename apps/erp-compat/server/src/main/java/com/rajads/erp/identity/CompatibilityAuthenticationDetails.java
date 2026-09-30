package com.rajads.erp.identity;

import java.util.Set;

/** Request-scoped company range supplied by the current identity authority. */
public record CompatibilityAuthenticationDetails(boolean allOperators, Set<Long> operatorIds) {
}
