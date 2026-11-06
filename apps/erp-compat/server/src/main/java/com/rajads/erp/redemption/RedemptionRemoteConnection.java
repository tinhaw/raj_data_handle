package com.rajads.erp.redemption;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

/** A market-specific remote account. Password, TOTP secret and refreshed session token are encrypted at rest. */
@Entity
@Table(name = "redemption_remote_connections")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionRemoteConnection {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    /** Legacy internal identifier retained for historical V7/V8 rows; operators configure only username. */
    @Column(nullable = false, unique = true, length = 60) private String code;
    @Column(nullable = false, length = 120) private String name;
    @Column(nullable = false, length = 120) private String username;
    @Column(name = "market_id", nullable = false) private Long marketId;
    /** Kept as a synchronized endpoint snapshot for V7 compatibility and remote-call efficiency. */
    @Column(name = "base_url", nullable = false, length = 500) private String baseUrl;
    @Column(name = "password_ciphertext", columnDefinition = "text") private String passwordCiphertext;
    @Column(name = "totp_secret_ciphertext", columnDefinition = "text") private String totpSecretCiphertext;
    @Column(name = "access_token_ciphertext", columnDefinition = "text") private String accessTokenCiphertext;
    @Column(name = "access_token_expires_at") private Instant accessTokenExpiresAt;
    @Column(name = "last_logged_in_at") private Instant lastLoggedInAt;
    @Column(nullable = false) private boolean enabled = true;
    @Column(name = "last_checked_at") private Instant lastCheckedAt;
    @Column(name = "last_error", length = 1000) private String lastError;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "updated_by") private Long updatedBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
