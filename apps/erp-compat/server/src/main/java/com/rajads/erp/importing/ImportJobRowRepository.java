package com.rajads.erp.importing;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ImportJobRowRepository extends JpaRepository<ImportJobRow, Long> {
    List<ImportJobRow> findByImportJobIdOrderBySourceSheetAscSourceRowAsc(Long importJobId);
}
