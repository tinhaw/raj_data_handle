package com.rajads.erp.redemption;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** A code belongs to the immutable market namespace of its issue. */
@Embeddable
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class RedemptionStoredCode {
    @Column(name = "code", nullable = false, length = 255)
    private String value;

    @Column(name = "remote_market_id", nullable = false)
    private Long marketId;

    public RedemptionStoredCode(Long marketId, String value) {
        this.marketId = marketId;
        this.value = value;
    }
}
