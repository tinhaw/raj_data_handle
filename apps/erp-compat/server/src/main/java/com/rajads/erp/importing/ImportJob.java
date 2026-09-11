package com.rajads.erp.importing;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

@Entity
@Table(name = "erp_compat_import_jobs")
@Getter @Setter @NoArgsConstructor
public class ImportJob {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "source_type", nullable = false) private String sourceType;
    @Column(name = "original_filename") private String originalFilename;
    @Column(name = "file_sha256", length = 64) private String fileSha256;
    @Column(nullable = false) private String status;
    @Column(name = "conflict_strategy", nullable = false) private String conflictStrategy = "SKIP_EXISTING";
    @Column(name = "total_rows", nullable = false) private Integer totalRows = 0;
    @Column(name = "valid_rows", nullable = false) private Integer validRows = 0;
    @Column(name = "warning_rows", nullable = false) private Integer warningRows = 0;
    @Column(name = "error_rows", nullable = false) private Integer errorRows = 0;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "committed_by") private Long committedBy;
    @Column(name = "committed_at") private Instant committedAt;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
