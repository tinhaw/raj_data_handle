package com.rajads.erp.operator;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class OperatorAccountTest {

    @Test
    void newAccountsDefaultServiceFeeCalculationToTransfer() {
        OperatorAccount account = new OperatorAccount();

        assertThat(account.getDefaultServiceFeeBasis()).isEqualTo("TRANSFER");
    }
}
