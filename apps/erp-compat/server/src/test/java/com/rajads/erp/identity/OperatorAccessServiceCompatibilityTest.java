package com.rajads.erp.identity;

import com.rajads.erp.shared.ApiException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;

class OperatorAccessServiceCompatibilityTest {
    @AfterEach
    void clearContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void usesMappedOnlineOperatorIdsWithoutReadingTheLegacyScopeTable() {
        AuthUser principal = new AuthUser(7L, "ledger-user", "", "Ledger User", true, false,
                Set.of("COMPATIBILITY_BRIDGED"), Set.of("BALANCE_VIEW"));
        UsernamePasswordAuthenticationToken authentication =
                UsernamePasswordAuthenticationToken.authenticated(
                        principal,
                        null,
                        principal.getAuthorities());
        authentication.setDetails(new CompatibilityAuthenticationDetails(false, Set.of(17L, 23L)));
        SecurityContextHolder.getContext().setAuthentication(authentication);
        UserOperatorScopeRepository legacyRepository = mock(UserOperatorScopeRepository.class);
        OperatorAccessService service = new OperatorAccessService(new CurrentUser(), legacyRepository);

        assertThat(service.hasAllOperators()).isFalse();
        assertThat(service.accessibleOperatorIds()).containsExactlyInAnyOrder(17L, 23L);
        service.requireAccess(17L);
        assertThatThrownBy(() -> service.requireAccess(99L))
                .isInstanceOf(ApiException.class)
                .hasMessage("没有该投放公司的数据权限");
        verifyNoInteractions(legacyRepository);
    }
}
