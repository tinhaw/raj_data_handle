package com.rajads.erp;

import com.rajads.erp.config.ErpProperties;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(properties = {
        "erp.compatibility.standalone-auth-enabled=false",
        "erp.compatibility.identity-url=http://localhost/identity",
        "erp.compatibility.remote-registry-url=http://localhost/remote-registry"
})
class CompatibilityModeContextTest {
    @Autowired
    private ErpProperties properties;

    @Test
    void sharedIdentityModeStillRegistersErpProperties() {
        assertThat(properties.businessZone()).isEqualTo("Asia/Shanghai");
    }
}
