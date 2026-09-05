package com.rajads.erp.redemption;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/** Operator-facing task that can contain one or more per-market execution batches. */
@Entity
@Table(name = "erp_compat_redemption_code_tasks")
@Getter
@Setter
@NoArgsConstructor
public class RedemptionCodeTask {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(name = "grouping_key", nullable = false, unique = true, length = 140) private String groupingKey;
    /** Business day in Shanghai used as the visible task-number prefix. */
    @Column(name = "task_date", nullable = false) private LocalDate taskDate;
    /** One-based task sequence within {@link #taskDate}; it is not the database primary key. */
    @Column(name = "daily_sequence", nullable = false) private Integer dailySequence;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;

    @PrePersist void created() { createdAt = Instant.now(); }

    public String taskNumber() {
        if (taskDate == null || dailySequence == null) return null;
        return taskDate.format(DateTimeFormatter.BASIC_ISO_DATE) + String.format(Locale.ROOT, "%04d", dailySequence);
    }
}
