package com.rajads.erp.balance;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class DailyBalanceTest {

    @Test
    void newDailyBalancesDefaultServiceFeeCalculationToTransfer() {
        DailyBalance balance = new DailyBalance();

        assertThat(balance.getServiceFeeBasis()).isEqualTo("TRANSFER");
    }
}
