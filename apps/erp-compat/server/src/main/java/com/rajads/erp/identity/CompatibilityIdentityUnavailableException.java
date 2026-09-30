package com.rajads.erp.identity;

public class CompatibilityIdentityUnavailableException extends RuntimeException {
    public CompatibilityIdentityUnavailableException(String message) {
        super(message);
    }

    public CompatibilityIdentityUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
