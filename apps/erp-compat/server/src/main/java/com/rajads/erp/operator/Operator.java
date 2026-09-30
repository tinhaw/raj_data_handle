package com.rajads.erp.operator;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.Instant;

@Entity
@Table(name = "erp_compat_operators")
@Getter
@Setter
@NoArgsConstructor
public class Operator {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) private Long id;
    @Column(nullable = false, unique = true, length = 50) private String code;
    @Column(nullable = false, length = 200) private String name;
    @Column(name = "operator_type", nullable = false, length = 20) private String operatorType = "COMPANY";
    @Column(nullable = false, length = 20) private String status = "ACTIVE";
    @Column(name = "contact_name", length = 120) private String contactName;
    @Column(name = "contact_value", length = 200) private String contactValue;
    @Column(columnDefinition = "text") private String remark;
    @Column(name = "created_by") private Long createdBy;
    @Column(name = "updated_by") private Long updatedBy;
    @Column(name = "created_at", nullable = false) private Instant createdAt;
    @Column(name = "updated_at", nullable = false) private Instant updatedAt;
    @Version @Column(name = "row_version", nullable = false) private Long rowVersion;

    @PrePersist void created() { Instant now = Instant.now(); createdAt = now; updatedAt = now; }
    @PreUpdate void updated() { updatedAt = Instant.now(); }
}
