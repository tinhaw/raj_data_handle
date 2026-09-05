package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;
import jakarta.persistence.EntityManager;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class RedemptionCodeStorageTest {
    @Test
    void refusesDuplicateCodesAndNeverOverwritesAnImportedGroup() {
        var entityManager = mock(EntityManager.class);
        var storage = new RedemptionCodeStorage(entityManager);
        var batch = new RedemptionCodeBatch();
        batch.setRemoteKeyNumber(2);
        var issue = new RedemptionCodeIssue();
        issue.setId(1L);
        assertThatThrownBy(() -> storage.store(issue, batch, List.of("A", "A")))
                .isInstanceOf(ApiException.class).hasMessageContaining("重复");
        issue.setCodes(List.of("A", "B"));
        assertThat(storage.store(issue, batch, List.of("B", "A"))).isZero();
        assertThatThrownBy(() -> storage.store(issue, batch, List.of("A", "C")))
                .isInstanceOf(ApiException.class).hasMessageContaining("不能覆盖");
        assertThat(issue.getCodes()).containsExactly("A", "B");
        verifyNoInteractions(entityManager);
    }

    @Test
    void refusesACodeAlreadyOwnedByAnotherGroup() {
        var entityManager = mock(EntityManager.class, RETURNS_DEEP_STUBS);
        when(entityManager.createQuery(anyString(), eq(Long.class))
                .setParameter("codes", List.of("TAKEN"))
                .setParameter("id", 1L).getSingleResult()).thenReturn(1L);
        var issue = new RedemptionCodeIssue();
        issue.setId(1L);
        assertThatThrownBy(() -> new RedemptionCodeStorage(entityManager)
                .store(issue, new RedemptionCodeBatch(), List.of("TAKEN")))
                .isInstanceOf(ApiException.class).hasMessageContaining("其他任务");
        assertThat(issue.getCodes()).isEmpty();
    }
}
