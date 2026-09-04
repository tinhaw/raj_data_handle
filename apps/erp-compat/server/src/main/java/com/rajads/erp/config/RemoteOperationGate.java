package com.rajads.erp.config;

import com.rajads.erp.shared.ApiException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Legacy-client guard for the isolated standalone regression fixture.
 *
 * <p>Production compatibility mode delegates confirmed redemption creation to
 * the main application's unified account executor and must never instantiate
 * the imported credential client.  This guard therefore only permits that
 * legacy client when the explicitly standalone profile is active.</p>
 */
@Component
public class RemoteOperationGate {
    private final boolean enabled;

    @Autowired
    public RemoteOperationGate(
            @Value("${erp.compatibility.standalone-auth-enabled:false}") boolean standaloneAuthEnabled) {
        this.enabled = standaloneAuthEnabled;
    }

    public void requireEnabled(String operation) {
        if (!enabled) {
            throw ApiException.forbidden("ERP 兼容模块的远端操作尚未启用：" + operation);
        }
    }
}
