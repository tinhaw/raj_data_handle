package com.rajads.erp.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "erp")
public record ErpProperties(Storage storage, BootstrapAdmin bootstrapAdmin, String businessZone, ImportSettings importSettings,
                            RemoteConnections remoteConnections) {
    public record Storage(String localPath) {
    }
    public record BootstrapAdmin(String username, String password) {
    }
    public record ImportSettings(Integer maxRows) {
    }
    /** Master key for database-stored remote-backend bearer tokens. It stays in the deployment secret environment only. */
    public record RemoteConnections(String encryptionKey) {
    }
}
