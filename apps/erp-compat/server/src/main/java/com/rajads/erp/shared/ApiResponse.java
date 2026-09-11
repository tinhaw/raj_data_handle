package com.rajads.erp.shared;

/** Success envelope shared by browser clients; errors use {@link ApiError}. */
public record ApiResponse<T>(T data) { }
