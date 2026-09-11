package com.rajads.erp.importing;

import com.rajads.erp.balance.BalanceDtos;
import jakarta.validation.constraints.NotBlank;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

public final class ImportDtos {
    private ImportDtos() { }
    public record PastePreviewRequest(@NotBlank String text, Long accountId, String conflictStrategy) { }
    public record ImportCommitRequest(String conflictStrategy) { }
    public record ImportJobResponse(Long id, String sourceType, String originalFilename, String fileSha256,
                                    Long createdBy, String status, String conflictStrategy, Integer totalRows,
                                    Integer validRows, Integer warningRows, Integer errorRows, Instant createdAt,
                                    Instant committedAt) { }
    public record ImportRowResponse(Long id, String sourceSheet, Integer sourceRow, String operatorName,
                                    Long operatorAccountId, LocalDate businessDate, String severity, String errorCode,
                                    String errorMessage, String action, Long targetDailyBalanceId,
                                    BalanceDtos.DailyBalanceUpsertRequest normalized) { }
    public record ImportPreviewResponse(ImportJobResponse job, List<ImportRowResponse> rows) { }
    public record ImportCommitResponse(ImportJobResponse job, int created, int updated, int skipped) { }
}
