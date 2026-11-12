package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

/** Historical inventory remains owned by the same canonical issue across generations. */
@Entity @Table(name="erp_compat_redemption_historical_codes")
@Getter @Setter
public class RedemptionHistoricalCode {
    @Id @GeneratedValue(strategy=GenerationType.IDENTITY) private Long id;
    @Column(name="recovery_id", nullable=false) private Long recoveryId;
    @Column(name="owner_issue_id", nullable=false) private Long ownerIssueId;
    @Column(name="remote_market_id", nullable=false) private Long remoteMarketId;
    @Column(name="configuration_id", nullable=false, length=255) private String configurationId;
    @Column(name="code_index", nullable=false) private int codeIndex;
    @Column(nullable=false, length=255) private String code;
}
