package com.rajads.erp.reporting;

import org.apache.poi.ss.usermodel.CellType;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class ReportExcelExporterTest {
    private final ReportExcelExporter exporter = new ReportExcelExporter();

    @Test
    void exportWritesTotalFormulasAndEscapesFormulaLikeText() throws Exception {
        BigDecimal value = new BigDecimal("12.34");
        ReportDtos.ReportRow row = new ReportDtos.ReportRow("=2026-07-01", "@USDT", value, value, value, value,
                value, value, value, value, value, value, value, value, 2, List.of("+warning"));
        byte[] workbook = exporter.export(new ReportDtos.ReportResponse("DAILY", true, List.of(row)));

        try (XSSFWorkbook parsed = new XSSFWorkbook(new ByteArrayInputStream(workbook))) {
            var sheet = parsed.getSheetAt(0);
            assertThat(sheet.getRow(1).getCell(0).getCellType()).isEqualTo(CellType.STRING);
            assertThat(sheet.getRow(1).getCell(0).getStringCellValue()).isEqualTo("'=2026-07-01");
            assertThat(sheet.getRow(1).getCell(1).getStringCellValue()).isEqualTo("'@USDT");
            assertThat(sheet.getRow(1).getCell(15).getStringCellValue()).isEqualTo("'+warning");
            assertThat(sheet.getRow(2).getCell(2).getCellFormula()).isEqualTo("SUM(C2:C2)");
            assertThat(sheet.getRow(2).getCell(13).getCellFormula()).isEqualTo("SUM(N2:N2)");
            assertThat(sheet.getRow(2).getCell(14).getCellFormula()).isEqualTo("SUM(O2:O2)");
        }
        assertThat(ReportExcelExporter.safeText(" \t=HYPERLINK(\"https://example.com\")"))
                .isEqualTo("' \t=HYPERLINK(\"https://example.com\")");
    }
}
