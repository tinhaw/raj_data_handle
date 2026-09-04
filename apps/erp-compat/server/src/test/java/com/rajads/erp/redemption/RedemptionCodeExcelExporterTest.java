package com.rajads.erp.redemption;

import org.apache.poi.ss.usermodel.IndexedColors;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class RedemptionCodeExcelExporterTest {
    private final RedemptionCodeExcelExporter exporter = new RedemptionCodeExcelExporter();

    @Test
    void exportsEveryCodeInSingleAndMultiMarketWorkbooks() throws Exception {
        var day = LocalDate.of(2026, 9, 5);
        var tier = new RedemptionDtos.TierResponse(7L, "首档", BigDecimal.valueOf(100),
                BigDecimal.valueOf(5), BigDecimal.valueOf(5), 1, 0L);
        var campaign = new RedemptionDtos.CampaignResponse(1L, "MULTI", "多码活动", "ACTIVE", 7,
                null, List.of(tier), 5, 0, 0L, null, null);
        var codes = List.of("CODE-A", "CODE-B", "CODE-C", "CODE-D", "CODE-E");
        var issue = new RedemptionDtos.CodeIssueResponse(9L, 1L, 7L, "首档", BigDecimal.valueOf(100),
                BigDecimal.valueOf(5), day, day.minusDays(7), day.minusDays(1), String.join("\n", codes),
                "GENERATED", null, null, null, 0L, BigDecimal.valueOf(5), 1L, "CODE_IMPORTED", "cfg-multi", null, List.of());
        for (var type : RedemptionCodeType.values()) {
            byte[] file = exporter.export(campaign, List.of(issue), day, day, "RajWin", type);
            try (var workbook = new XSSFWorkbook(new ByteArrayInputStream(file))) {
                int firstRow = type == RedemptionCodeType.PREVIOUS_DAY_DEPOSIT ? 3 : 4;
                int step = type == RedemptionCodeType.PREVIOUS_DAY_DEPOSIT ? 1 : 2;
                for (int index = 0; index < codes.size(); index++) {
                    assertThat(workbook.getSheetAt(0).getRow(firstRow + index * step).getCell(1).getStringCellValue())
                            .isEqualTo(codes.get(index));
                }
            }
        }
        var markets = List.of(
                new RedemptionCodeExcelExporter.MarketSheet("RajWin", campaign, RedemptionCodeType.SEVEN_DAY_DEPOSIT, List.of(issue), day, day),
                new RedemptionCodeExcelExporter.MarketSheet("RajLuck", campaign, RedemptionCodeType.PREVIOUS_DAY_DEPOSIT, List.of(issue), day, day));
        try (var workbook = new XSSFWorkbook(new ByteArrayInputStream(exporter.exportMultiMarket(markets)))) {
            assertThat(workbook.getNumberOfSheets()).isEqualTo(3);
            for (var sheet : workbook) {
                var exported = new java.util.ArrayList<String>();
                for (var row : sheet) {
                    var cell = row.getCell(1);
                    if (cell != null && cell.getCellType() == org.apache.poi.ss.usermodel.CellType.STRING
                            && cell.getStringCellValue().startsWith("CODE-")) exported.add(cell.getStringCellValue());
                }
                assertThat(exported).containsAll(codes).hasSize(sheet.getSheetName().equals("All") ? 10 : 5);
            }
        }
    }

    @Test
    void writesTheReferenceFixedHeaderCopyWhileKeepingDepositHeadersDynamic() throws Exception {
        RedemptionDtos.TierResponse tier = new RedemptionDtos.TierResponse(7L, "首档", new BigDecimal("100"),
                new BigDecimal("5"), new BigDecimal("17"), 1, 0L);
        RedemptionDtos.TierResponse secondTier = new RedemptionDtos.TierResponse(8L, "次档", new BigDecimal("555"),
                new BigDecimal("7"), new BigDecimal("57"), 2, 0L);
        RedemptionDtos.CampaignResponse campaign = new RedemptionDtos.CampaignResponse(1L, "DEPOSIT_7D", "八月充值活动",
                "ACTIVE", 7, null, List.of(tier, secondTier), 1, 0, 0L, null, null);
        RedemptionDtos.CodeIssueResponse issue = new RedemptionDtos.CodeIssueResponse(9L, 1L, 7L, "首档",
                new BigDecimal("100"), new BigDecimal("5"), LocalDate.of(2026, 8, 14),
                LocalDate.of(2026, 8, 7), LocalDate.of(2026, 8, 13), "=ABC123", "GENERATED", null, null, null, 0L,
                new BigDecimal("17"), 1L, "CODE_IMPORTED", "1555", null, List.of());

        byte[] file = exporter.export(campaign, List.of(issue), LocalDate.of(2026, 8, 14), LocalDate.of(2026, 8, 15));

        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(file))) {
            var sheet = workbook.getSheetAt(0);
            assertThat(sheet.getSheetName()).isEqualTo("Bonus Codes");
            assertThat(sheet.getMergedRegions()).hasSize(6);
            assertThat(sheet.getRow(0).getCell(0).getStringCellValue()).isEqualTo("Ek Deposit = 7 Free Bonuses! 🎉 (Har Din Sirf Ek Baar) 🎁");
            assertThat(sheet.getRow(1).getCell(0).getStringCellValue()).isEqualTo("Date");
            assertThat(sheet.getRow(1).getCell(1).getStringCellValue()).isEqualTo("Deposit:>100");
            assertThat(sheet.getRow(1).getCell(2).getStringCellValue()).isEqualTo("Deposit:>555");
            assertThat(sheet.getRow(2).getCell(1).getStringCellValue()).isEqualTo("Daily Bonus:₹3-17");
            assertThat(sheet.getRow(2).getCell(2).getStringCellValue()).isEqualTo("Daily Bonus:₹7-57");
            assertThat(sheet.getRow(3).getCell(1).getStringCellValue())
                    .isEqualTo("Aaj ₹100 deposit karo,\naur agle din se 7 din tak\nfree bonus pao!\n₹21 - ₹119 🤑");
            assertThat(sheet.getRow(3).getCell(2).getStringCellValue())
                    .isEqualTo("Aaj ₹500 deposit karo,\naur agle din se 7 din tak\nfree bonus pao!\n₹49 - ₹399 🤑");
            assertThat(sheet.getRow(4).getCell(0).getStringCellValue()).isEqualTo("Bonus Claim Time 14/08 ⏰");
            assertThat(sheet.getRow(5).getCell(0).getStringCellValue()).isEqualTo("Deposit time: (07/08—13/08)");
            assertThat(sheet.getRow(4).getCell(0).getCellStyle().getFillForegroundColor()).isEqualTo(IndexedColors.BRIGHT_GREEN.getIndex());
            assertThat(sheet.getRow(4).getCell(1).getStringCellValue()).isEqualTo("'=ABC123");
            assertThat(sheet.getRow(6).getCell(1).getStringCellValue()).isEqualTo("Pending");
        }
    }

    @Test
    void usesTheRemoteMarketNameForTheWorksheet() throws Exception {
        RedemptionDtos.TierResponse tier = new RedemptionDtos.TierResponse(7L, "首档", new BigDecimal("100"),
                new BigDecimal("5"), new BigDecimal("17"), 1, 0L);
        RedemptionDtos.CampaignResponse campaign = new RedemptionDtos.CampaignResponse(1L, "DEPOSIT_7D", "八月充值活动",
                "ACTIVE", 7, null, List.of(tier), 1, 0, 0L, null, null);

        byte[] file = exporter.export(campaign, List.of(), LocalDate.of(2026, 8, 14), LocalDate.of(2026, 8, 14), "RajSpin");

        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(file))) {
            assertThat(workbook.getSheetAt(0).getSheetName()).isEqualTo("RajSpin");
        }
    }
}
