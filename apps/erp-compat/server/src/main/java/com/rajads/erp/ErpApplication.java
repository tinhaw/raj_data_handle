package com.rajads.erp;

import com.rajads.erp.config.ErpProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(ErpProperties.class)
public class ErpApplication {
    public static void main(String[] args) {
        requireExplicitCompatibilityActivation(System.getenv());
        SpringApplication.run(ErpApplication.class, args);
    }

    static void requireExplicitCompatibilityActivation(java.util.Map<String, String> environment) {
        if (!Boolean.parseBoolean(environment.getOrDefault("ERP_COMPATIBILITY_MODE_ENABLED", "false"))) {
            throw new IllegalStateException(
                    "ERP compatibility service is an imported migration snapshot and is disabled by default. "
                            + "Set ERP_COMPATIBILITY_MODE_ENABLED=true only after the shared identity, shared remote-account "
                            + "and Alembic schema adapters have passed their compatibility tests.");
        }
    }
}
