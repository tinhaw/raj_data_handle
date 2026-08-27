package com.rajads.erp.config;

import com.rajads.erp.shared.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Global migration guard for every call that can reach a remote Raj backend.
 *
 * <p>This switch is intentionally independent from application startup and
 * method permissions. A migrated user grant is never sufficient on its own to
 * enable connection checks, tag reads/syncs or redemption execution.</p>
 */
@Component
public class RemoteOperationGate {
    private final boolean enabled;

    @Autowired
    public RemoteOperationGate(
            @Value("${erp.compatibility.remote-operations-enabled:false}") boolean enabled,
            @Value("${erp.compatibility.standalone-auth-enabled:false}") boolean standaloneAuthEnabled) {
        // Compatibility mode delegates every authorised remote operation to
        // the main application's unified-account runner. The imported Spring
        // client must never read a second credential/session store.
        this.enabled = enabled && standaloneAuthEnabled;
    }

    public RemoteOperationGate(boolean enabled) {
        this.enabled = enabled;
    }

    public void requireEnabled(String operation) {
        if (!enabled) {
            throw ApiException.forbidden("ERP 兼容模块的远端操作尚未启用：" + operation);
        }
    }
}
