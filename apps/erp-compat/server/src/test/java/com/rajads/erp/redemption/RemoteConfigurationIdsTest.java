package com.rajads.erp.redemption;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.*;

class RemoteConfigurationIdsTest {
    @org.junit.jupiter.api.Test
    void reviewRequiresBothSentinelAndExplicitBusinessMessage() {
        String message = "你提交的配置触发风控规则，需主管审核通过后才可以生成配置，配置生成后需自行发布配置兑换码才生效";
        assertThatThrownBy(() -> RemoteConfigurationIds.requireCreated("-1", message))
                .hasMessageContaining("待远端主管审核");
        assertThatThrownBy(() -> RemoteConfigurationIds.requireCreated("-1", "success"))
                .hasMessageContaining("无效配置 ID");
        assertThatThrownBy(() -> RemoteConfigurationIds.requireCreated("0", message))
                .hasMessageContaining("无效配置 ID");
        assertThat(RemoteConfigurationIds.requireCreated("123", message)).isEqualTo("123");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" ", "-1", "-2", "0", "00", "+1", "1.5", "1e3", "null", "false", "true", "NaN"})
    void rejectsInvalidIds(String id) {
        assertThat(RemoteConfigurationIds.isValid(id)).isFalse();
        assertThatThrownBy(() -> RemoteConfigurationIds.requireCreated(id))
                .isInstanceOf(com.rajads.erp.shared.ApiException.class).hasMessageContaining("远端创建结果未确认");
    }

    @ParameterizedTest
    @ValueSource(strings = {"1", "001", "99999999999999999999999999999", "cfg-1", "receipt-123", "manual-scope-id"})
    void preservesPositiveAndOpaqueIds(String id) {
        assertThat(RemoteConfigurationIds.requireCreated(id)).isEqualTo(id);
    }
}
