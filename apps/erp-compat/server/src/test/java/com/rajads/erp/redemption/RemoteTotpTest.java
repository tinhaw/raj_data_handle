package com.rajads.erp.redemption;

import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

class RemoteTotpTest {
    @Test
    void generatesRfc6238CompatibleCodeFromBase32SecretAndOtpAuthUri() {
        Instant instant = Instant.ofEpochSecond(59);
        assertThat(RemoteTotp.generate("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", instant)).isEqualTo("287082");
        assertThat(RemoteTotp.generate("otpauth://totp/RajWin?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", instant)).isEqualTo("287082");
    }
}
