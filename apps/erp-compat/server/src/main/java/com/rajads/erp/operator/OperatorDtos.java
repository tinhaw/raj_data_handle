package com.rajads.erp.operator;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

public final class OperatorDtos {
    private OperatorDtos() { }

    /**
     * The persisted code remains an internal compatibility key.  New delivery
     * companies are identified by name in the product UI, so callers no
     * longer need to provide a code.
     */
    public record OperatorRequest(@Size(max = 50) String code,
                                  @NotBlank @Size(max = 200) String name,
                                  String operatorType, String contactName, String contactValue, String remark) { }
    public record OperatorPatchRequest(String name, String operatorType, String contactName, String contactValue,
                                       String remark, Long rowVersion) { }
    public record DisableRequest(String reason, Long rowVersion) { }
    public record DeleteRequest(String reason, Long rowVersion, boolean purgeHistory) { }
    /**
     * A persisted account is presented as a delivery line.  Code and the
     * calculation settings are retained for historical compatibility but are
     * no longer required when creating a line.
     */
    public record AccountRequest(@Size(max = 50) String code,
                                 @NotBlank @Size(max = 120) String name,
                                 String asset, String network, String walletAddress, LocalDate startDate,
                                 BigDecimal defaultExchangeLossRate, String defaultExchangeLossBasis,
                                 BigDecimal defaultServiceFeeRate, String defaultServiceFeeBasis,
                                 Integer calculationScale) { }
    public record AccountPatchRequest(String name, String network, String walletAddress, LocalDate startDate,
                                      BigDecimal defaultExchangeLossRate, String defaultExchangeLossBasis,
                                      BigDecimal defaultServiceFeeRate, String defaultServiceFeeBasis,
                                      Integer calculationScale, Long rowVersion) { }
    public record OperatorResponse(Long id, String code, String name, String operatorType, String status,
                                   String contactName, String contactValue, String remark, Long rowVersion,
                                   Instant createdAt, Instant updatedAt) { }
    public record AccountResponse(Long id, Long operatorId, String companyName, String displayName,
                                  String code, String name, String asset, String network,
                                  String walletAddress, LocalDate startDate, BigDecimal defaultExchangeLossRate,
                                  String defaultExchangeLossBasis, BigDecimal defaultServiceFeeRate,
                                  String defaultServiceFeeBasis, Integer calculationScale, String status,
                                  Long rowVersion) { }
    public record OperatorDetailResponse(OperatorResponse operator, List<AccountResponse> accounts) { }
}
