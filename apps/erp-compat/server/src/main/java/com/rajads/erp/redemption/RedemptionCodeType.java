package com.rajads.erp.redemption;

/** Determines the recharge window and remote audience convention for a code group. */
public enum RedemptionCodeType {
    /** Use the existing fixed tags for the seven days before the claim date. */
    SEVEN_DAY_DEPOSIT,
    /** Use daily-recharge tags from the day before the claim date. */
    PREVIOUS_DAY_DEPOSIT
}
