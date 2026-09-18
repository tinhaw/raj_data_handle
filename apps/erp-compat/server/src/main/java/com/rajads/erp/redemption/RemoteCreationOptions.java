package com.rajads.erp.redemption;

import java.math.BigDecimal;

/** Immutable per-batch snapshot of the remote gift-code configuration options. */
public record RemoteCreationOptions(
        String publishEnvironment,
        int flowTimes,
        int creationIntervalSeconds,
        BigDecimal activityRecharge,
        Integer activityRechargeCount,
        Long activityId,
        int keyNumber,
        int singleUserLimit,
        int singleKeyLimit,
        boolean requireBindBankCard,
        boolean requireBindPhone,
        boolean checkUuid,
        int uuidRewardLimit,
        boolean checkLoginIp,
        int loginIpRewardLimit,
        boolean checkRegisterIp,
        int registerIpRewardLimit) { }
