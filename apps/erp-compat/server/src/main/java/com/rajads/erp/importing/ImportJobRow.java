package com.rajads.erp.importing;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDate;

@Entity
@Table(name = "erp_compat_import_job_rows")
@Getter @Setter @NoArgsConstructor
public class ImportJobRow {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "import_job_id", nullable = false) private Long importJobId;
    @Column(name = "source_sheet") private String sourceSheet;
    @Column(name = "source_row") private Integer sourceRow;
    @Column(name = "source_json", columnDefinition = "text") private String sourceJson;
    @Column(name = "normalized_json", columnDefinition = "text") private String normalizedJson;
    @Column(name = "operator_name") private String operatorName;
    @Column(name = "operator_account_id") private Long operatorAccountId;
    @Column(name = "business_date") private LocalDate businessDate;
    @Column(nullable = false) private String severity = "OK";
    @Column(name = "error_code") private String errorCode;
    @Column(name = "error_message", length = 1000) private String errorMessage;
    @Column(name = "action") private String action;
    @Column(name = "target_daily_balance_id") private Long targetDailyBalanceId;
    /**
     * Snapshot of the conflicting record at preview time.  UPDATE_DRAFT imports must match this snapshot before
     * they are allowed to update, otherwise a later edit could be overwritten silently.
     */
    @Column(name = "preview_daily_balance_id") private Long previewDailyBalanceId;
    @Column(name = "preview_row_version") private Long previewRowVersion;
}
