package com.rajads.erp.importing;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ImportJobRepository extends JpaRepository<ImportJob, Long> {
    boolean existsByFileSha256AndStatus(String fileSha256, String status);
    List<ImportJob> findByCreatedByOrderByCreatedAtDesc(Long createdBy);
    List<ImportJob> findAllByOrderByCreatedAtDesc();
}
