package com.rajads.erp.redemption;

import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class RedemptionMultiMarketExcelExporterTest {
    private final RedemptionCodeExcelExporter exporter = new RedemptionCodeExcelExporter();

    @Test
    void writesAllMarketsToTheCombinedSheetAndTheirOwnWorksheets() throws Exception {
        LocalDate date = LocalDate.of(2026, 8, 18);
        byte[] file = exporter.exportMultiMarket(List.of(
                new RedemptionCodeExcelExporter.MarketSheet("RajWin", campaign("WIN"), RedemptionCodeType.SEVEN_DAY_DEPOSIT, List.of(), date, date),
                new RedemptionCodeExcelExporter.MarketSheet("RajLuck", campaign("LUCK"), RedemptionCodeType.SEVEN_DAY_DEPOSIT, List.of(), date, date)));

        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(file))) {
            assertThat(workbook.getNumberOfSheets()).isEqualTo(3);
            assertThat(workbook.getSheetAt(0).getSheetName()).isEqualTo("All");
            assertThat(workbook.getSheetAt(1).getSheetName()).isEqualTo("RajWin");
            assertThat(workbook.getSheetAt(2).getSheetName()).isEqualTo("RajLuck");
            assertThat(workbook.getSheet("All").getRow(0).getCell(0).getStringCellValue()).contains("Free Bonuses");
            assertThat(workbook.getSheet("All").getRow(9).getCell(0).getStringCellValue()).contains("Free Bonuses");
        }
    }

    @Test
    void writesDailyRechargeUsingTheCompactDepositReportLayout() throws Exception {
        LocalDate date = LocalDate.of(2026, 8, 18);
        RedemptionDtos.TierResponse tier = new RedemptionDtos.TierResponse(7L, "所有用户", BigDecimal.ZERO,
                new BigDecimal("1"), new BigDecimal("3"), 1, 0L);
        RedemptionDtos.CampaignResponse campaign = new RedemptionDtos.CampaignResponse(1L, "DAILY", "日充值",
                "ACTIVE", 1, null, List.of(tier), 1, 0, 0L, null, null);
        RedemptionDtos.CodeIssueResponse issue = new RedemptionDtos.CodeIssueResponse(9L, 1L, 7L, "所有用户",
                BigDecimal.ZERO, new BigDecimal("1"), date, date.minusDays(1), date.minusDays(1), "ABC123", "GENERATED",
                null, null, null, 0L, new BigDecimal("3"), 1L, "CODE_IMPORTED", "1555", null, List.of());
        byte[] file = exporter.exportMultiMarket(List.of(
                new RedemptionCodeExcelExporter.MarketSheet("RajWin", campaign, RedemptionCodeType.PREVIOUS_DAY_DEPOSIT,
                        List.of(issue), date, date)));

        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(file))) {
            var sheet = workbook.getSheet("RajWin");
            assertThat(sheet.getMergedRegions()).hasSize(1);
            assertThat(sheet.getRow(0).getCell(0).getStringCellValue()).isEqualTo("win");
            assertThat(sheet.getRow(2).getCell(0).getStringCellValue()).isEqualTo("日期");
            assertThat(sheet.getRow(2).getCell(1).getStringCellValue()).isEqualTo("deposit0");
            assertThat(sheet.getRow(3).getCell(0).getDateCellValue()).isEqualTo(java.sql.Date.valueOf(date));
            assertThat(sheet.getRow(3).getCell(1).getStringCellValue()).isEqualTo("ABC123");
            assertThat(sheet.getRow(0).getCell(0).getCellStyle().getFillForegroundColor())
                    .isEqualTo(org.apache.poi.ss.usermodel.IndexedColors.YELLOW.getIndex());
        }
    }

    @Test
    void writesAgentTemplateWithCombinedAndPerMarketSheets() throws Exception {
        LocalDate claimDate = LocalDate.of(2026, 9, 1);
        RedemptionDtos.TierResponse allUsers = new RedemptionDtos.TierResponse(7L, "全部用户", BigDecimal.ZERO,
                new BigDecimal("1"), new BigDecimal("3"), 1, 0L);
        RedemptionDtos.TierResponse depositTwoHundred = new RedemptionDtos.TierResponse(8L, "存款200", new BigDecimal("200"),
                new BigDecimal("7"), new BigDecimal("9"), 2, 0L);
        RedemptionDtos.CampaignResponse campaign = new RedemptionDtos.CampaignResponse(1L, "AGENT", "代理", "ACTIVE", 7,
                null, List.of(allUsers, depositTwoHundred), 1, 0, 0L, null, null);
        RedemptionDtos.CodeIssueResponse allUsersIssue = new RedemptionDtos.CodeIssueResponse(9L, 1L, 7L, "全部用户",
                BigDecimal.ZERO, new BigDecimal("1"), claimDate, claimDate.minusDays(7), claimDate.minusDays(1), "ALL-001\nALL-002",
                "GENERATED", null, null, null, 0L, new BigDecimal("3"), 1L, "CODE_IMPORTED", "config-all", null, List.of());
        RedemptionDtos.CodeIssueResponse depositIssue = new RedemptionDtos.CodeIssueResponse(10L, 1L, 8L, "存款200",
                new BigDecimal("200"), new BigDecimal("7"), claimDate, claimDate.minusDays(7), claimDate.minusDays(1), "DEP-001",
                "GENERATED", null, null, null, 0L, new BigDecimal("9"), 1L, "CODE_IMPORTED", "config-200", null, List.of(901027L));

        byte[] file = exporter.exportMultiMarket(List.of(
                new RedemptionCodeExcelExporter.MarketSheet("RajWin", campaign, RedemptionCodeType.AGENT,
                        List.of(allUsersIssue, depositIssue), claimDate, claimDate, 1),
                new RedemptionCodeExcelExporter.MarketSheet("RajLuck", campaign, RedemptionCodeType.AGENT,
                        List.of(allUsersIssue, depositIssue), claimDate, claimDate, 1)));

        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(file))) {
            var sheetNames = new java.util.ArrayList<String>();
            workbook.forEach(sheet -> sheetNames.add(sheet.getSheetName()));
            assertThat(sheetNames).containsExactly("全部盘口", "RajWin", "RajLuck");
            var combined = workbook.getSheet("全部盘口");
            assertThat(combined.getRow(0).getCell(0).getStringCellValue()).isEqualTo("win");
            assertThat(combined.getRow(0).getCell(5).getStringCellValue()).isEqualTo("luck");
            assertThat(combined.getRow(1).getCell(0).getStringCellValue()).isEqualTo("兑换码组描述");
            assertThat(combined.getRow(1).getCell(1).getStringCellValue()).isEqualTo("兑换码号码");
            assertThat(combined.getRow(2).getCell(0).getStringCellValue()).isEqualTo("9-02代理全部");
            assertThat(combined.getRow(2).getCell(1).getStringCellValue()).isEqualTo("ALL-001");
            assertThat(combined.getRow(2).getCell(2).getStringCellValue()).isEqualTo("9-02代理存款200");
            assertThat(combined.getRow(2).getCell(3).getStringCellValue()).isEqualTo("DEP-001");
            assertThat(combined.getRow(3).getCell(1).getStringCellValue()).isEqualTo("ALL-002");
            assertThat(workbook.getSheet("RajWin").getRow(2).getCell(2).getStringCellValue()).isEqualTo("9-02代理存款200");
        }
    }

    private RedemptionDtos.CampaignResponse campaign(String code) {
        RedemptionDtos.TierResponse tier = new RedemptionDtos.TierResponse(7L, "首档", new BigDecimal("100"),
                new BigDecimal("5"), new BigDecimal("17"), 1, 0L);
        return new RedemptionDtos.CampaignResponse(1L, code, code, "ACTIVE", 7, null, List.of(tier), 1, 0, 0L, null, null);
    }
}
