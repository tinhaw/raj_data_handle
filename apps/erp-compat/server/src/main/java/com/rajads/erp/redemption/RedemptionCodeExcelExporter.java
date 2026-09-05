package com.rajads.erp.redemption;

import org.apache.poi.ss.usermodel.*;
import org.apache.poi.ss.util.CellRangeAddress;
import org.apache.poi.ss.util.WorkbookUtil;
import org.apache.poi.xssf.usermodel.XSSFCellStyle;
import org.apache.poi.xssf.usermodel.XSSFColor;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.stereotype.Component;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Produces the English, date-by-tier code sheet supplied to players. */
@Component
public class RedemptionCodeExcelExporter {
    private static final String DEFAULT_SHEET_NAME = "Bonus Codes";
    private static final DateTimeFormatter SHORT_DATE = DateTimeFormatter.ofPattern("dd/MM");
    private static final List<String> PLAYER_DAILY_BONUSES = List.of(
            "Daily Bonus:₹3-17", "Daily Bonus:₹7-57", "Daily Bonus:₹15-177", "Daily  Bonus:₹27-377", "Daily Bonus:₹57-777"
    );
    private static final List<String> PLAYER_TIER_MESSAGES = List.of(
            "Aaj ₹100 deposit karo,\naur agle din se 7 din tak\nfree bonus pao!\n₹21 - ₹119 🤑",
            "Aaj ₹500 deposit karo,\naur agle din se 7 din tak\nfree bonus pao!\n₹49 - ₹399 🤑",
            "Aaj ₹2000 deposit\nkaro, aur agle din se\n7 din tak free bonus\npao!\n₹105- ₹1239 🤑",
            "Aaj ₹5000 deposit\nkaro, aur agle din se\n7 din tak free bonus\npao!\n₹189 - ₹2639 🤑",
            "Aaj ₹10000 deposit\nkaro, aur agle din se\n7 din tak free bonus\npao!\n₹399 - ₹5439 🤑"
    );

    /** One independently configured market is rendered to one worksheet. */
    public record MarketSheet(String sheetName, RedemptionDtos.CampaignResponse campaign, RedemptionCodeType redemptionType,
                              List<RedemptionDtos.CodeIssueResponse> issues, LocalDate from, LocalDate to,
                              Integer validFromDayOffset) {
        public MarketSheet(String sheetName, RedemptionDtos.CampaignResponse campaign, RedemptionCodeType redemptionType,
                           List<RedemptionDtos.CodeIssueResponse> issues, LocalDate from, LocalDate to) {
            this(sheetName, campaign, redemptionType, issues, from, to, 0);
        }

        int effectiveFromDayOffset() {
            return validFromDayOffset == null ? 0 : validFromDayOffset;
        }
    }

    public byte[] export(RedemptionDtos.CampaignResponse campaign, List<RedemptionDtos.CodeIssueResponse> issues,
                         LocalDate from, LocalDate to) {
        return export(campaign, issues, from, to, DEFAULT_SHEET_NAME);
    }

    public byte[] export(RedemptionDtos.CampaignResponse campaign, List<RedemptionDtos.CodeIssueResponse> issues,
                         LocalDate from, LocalDate to, String sheetName) {
        return export(campaign, issues, from, to, sheetName, RedemptionCodeType.SEVEN_DAY_DEPOSIT);
    }

    public byte[] export(RedemptionDtos.CampaignResponse campaign, List<RedemptionDtos.CodeIssueResponse> issues,
                         LocalDate from, LocalDate to, String sheetName, RedemptionCodeType redemptionType) {
        return export(campaign, issues, from, to, sheetName, redemptionType, 0);
    }

    public byte[] export(RedemptionDtos.CampaignResponse campaign, List<RedemptionDtos.CodeIssueResponse> issues,
                         LocalDate from, LocalDate to, String sheetName, RedemptionCodeType redemptionType,
                         Integer validFromDayOffset) {
        if (redemptionType == RedemptionCodeType.AGENT) {
            return exportMultiMarket(List.of(new MarketSheet(sheetName, campaign, redemptionType, issues, from, to,
                    validFromDayOffset)));
        }
        try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet(safeSheetName(sheetName));
            CellStyle title = titleStyle(workbook);
            CellStyle tierHeader = tierHeaderStyle(workbook);
            CellStyle dateHeader = dateHeaderStyle(workbook);
            CellStyle claimTime = claimTimeStyle(workbook);
            CellStyle depositTime = depositTimeStyle(workbook);
            CellStyle code = codeStyle(workbook);
            CellStyle failed = failedStyle(workbook);
            MarketSheet marketSheet = new MarketSheet(sheetName, campaign, redemptionType, issues, from, to, validFromDayOffset);
            if (isAgent(marketSheet)) {
                writeAgentMarketBlock(sheet, marketSheet, 0, agentTitleStyle(workbook), agentHeaderStyle(workbook),
                        agentDataStyle(workbook), agentFailedStyle(workbook));
                sheet.createFreezePane(0, 2);
            } else if (isDailyRecharge(marketSheet)) {
                writeDailyRechargeSheet(sheet, marketSheet, 0, dailyTitleStyle(workbook), dailyHeaderStyle(workbook),
                        dailyDateStyle(workbook), dailyCodeStyle(workbook), dailyFailedStyle(workbook));
            } else {
                writeMarketSheet(sheet, marketSheet, 0, title, tierHeader, dateHeader, claimTime, depositTime, code, failed);
            }
            workbook.write(output);
            return output.toByteArray();
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to create redemption code Excel", exception);
        }
    }

    /** Produces one workbook for a multi-market creation, including an All sheet plus each market sheet. */
    public byte[] exportMultiMarket(List<MarketSheet> marketSheets) {
        if (marketSheets == null || marketSheets.isEmpty()) throw new IllegalArgumentException("At least one market sheet is required");
        try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            if (marketSheets.stream().allMatch(this::isAgent)) {
                writeAgentMultiMarketWorkbook(workbook, marketSheets);
                workbook.write(output);
                return output.toByteArray();
            }
            CellStyle title = titleStyle(workbook);
            CellStyle tierHeader = tierHeaderStyle(workbook);
            CellStyle dateHeader = dateHeaderStyle(workbook);
            CellStyle claimTime = claimTimeStyle(workbook);
            CellStyle depositTime = depositTimeStyle(workbook);
            CellStyle code = codeStyle(workbook);
            CellStyle failed = failedStyle(workbook);
            CellStyle dailyTitle = dailyTitleStyle(workbook);
            CellStyle dailyHeader = dailyHeaderStyle(workbook);
            CellStyle dailyDate = dailyDateStyle(workbook);
            CellStyle dailyCode = dailyCodeStyle(workbook);
            CellStyle dailyFailed = dailyFailedStyle(workbook);
            Set<String> usedSheetNames = new HashSet<>();
            Sheet all = workbook.createSheet("All");
            usedSheetNames.add("All");
            int allRowIndex = 0;

            for (MarketSheet marketSheet : marketSheets) {
                Sheet sheet = workbook.createSheet(uniqueSheetName(marketSheet.sheetName(), usedSheetNames));
                if (isDailyRecharge(marketSheet)) {
                    writeDailyRechargeSheet(sheet, marketSheet, 0, dailyTitle, dailyHeader, dailyDate, dailyCode, dailyFailed);
                    allRowIndex = writeDailyRechargeSheet(all, marketSheet, allRowIndex, dailyTitle, dailyHeader, dailyDate, dailyCode, dailyFailed) + 3;
                } else {
                    writeMarketSheet(sheet, marketSheet, 0, title, tierHeader, dateHeader, claimTime, depositTime, code, failed);
                    allRowIndex = writeMarketSheet(all, marketSheet, allRowIndex, title, tierHeader, dateHeader, claimTime, depositTime, code, failed) + 3;
                }
            }
            workbook.write(output);
            return output.toByteArray();
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to create multi-market redemption code Excel", exception);
        }
    }

    /** Writes one market's exact worksheet layout at the requested row; used to compose the All worksheet. */
    private int writeMarketSheet(Sheet sheet, MarketSheet marketSheet, int startRow, CellStyle title, CellStyle tierHeader,
                                 CellStyle dateHeader, CellStyle claimTime, CellStyle depositTime, CellStyle code, CellStyle failed) {
        RedemptionDtos.CampaignResponse campaign = marketSheet.campaign();
        int lastColumn = campaign.tiers().size();
        Row titleRow = sheet.createRow(startRow);
        titleRow.setHeightInPoints(24);
        Cell heading = titleRow.createCell(0);
        heading.setCellValue(safeText("Ek Deposit = " + campaign.lookbackDays() + " Free Bonuses! 🎉 (Har Din Sirf Ek Baar) 🎁"));
        heading.setCellStyle(title);
        sheet.addMergedRegion(new CellRangeAddress(startRow, startRow, 0, lastColumn));

        Row depositHeader = sheet.createRow(startRow + 1);
        Row dailyBonusHeader = sheet.createRow(startRow + 2);
        Row tierMessageHeader = sheet.createRow(startRow + 3);
        depositHeader.setHeightInPoints(19);
        dailyBonusHeader.setHeightInPoints(19);
        tierMessageHeader.setHeightInPoints(83);
        Cell dateHeaderCell = depositHeader.createCell(0);
        dateHeaderCell.setCellValue("Date");
        dateHeaderCell.setCellStyle(dateHeader);
        dailyBonusHeader.createCell(0).setCellStyle(dateHeader);
        tierMessageHeader.createCell(0).setCellStyle(dateHeader);
        sheet.addMergedRegion(new CellRangeAddress(startRow + 1, startRow + 3, 0, 0));
        for (int index = 0; index < campaign.tiers().size(); index++) {
            RedemptionDtos.TierResponse tier = campaign.tiers().get(index);
            Cell depositCell = depositHeader.createCell(index + 1);
            depositCell.setCellValue(safeText(depositHeaderText(tier)));
            depositCell.setCellStyle(tierHeader);
            Cell dailyBonusCell = dailyBonusHeader.createCell(index + 1);
            dailyBonusCell.setCellValue(safeText(dailyBonusText(index, tier)));
            dailyBonusCell.setCellStyle(tierHeader);
            Cell messageCell = tierMessageHeader.createCell(index + 1);
            messageCell.setCellValue(safeText(tierMessageText(index, campaign.lookbackDays(), tier)));
            messageCell.setCellStyle(tierHeader);
        }

        Map<String, RedemptionDtos.CodeIssueResponse> codes = new HashMap<>();
        for (RedemptionDtos.CodeIssueResponse issue : marketSheet.issues()) {
            codes.put(issue.claimDate() + ":" + issue.campaignTierId(), issue);
        }
        Map<Long, List<String>> importedCodes = importedCodeMap(marketSheet.issues());
        int rowIndex = startRow + 4;
        for (LocalDate date = marketSheet.from(); !date.isAfter(marketSheet.to()); date = date.plusDays(1)) {
            LocalDate depositStart = date.minusDays(campaign.lookbackDays());
            LocalDate depositEnd = date.minusDays(1);
            int codeCount = codesOnDate(marketSheet.issues(), importedCodes, date);
            for (int codeIndex = 0; codeIndex < codeCount; codeIndex++) {
                Row claimRow = sheet.createRow(rowIndex);
                Row depositRow = sheet.createRow(rowIndex + 1);
                claimRow.setHeightInPoints(21);
                depositRow.setHeightInPoints(30);

                Cell claimCell = claimRow.createCell(0);
                claimCell.setCellValue("Bonus Claim Time " + SHORT_DATE.format(date) + " ⏰");
                claimCell.setCellStyle(claimTime);
                Cell depositCell = depositRow.createCell(0);
                depositCell.setCellValue("Deposit time: (" + SHORT_DATE.format(depositStart) + "—" + SHORT_DATE.format(depositEnd) + ")");
                depositCell.setCellStyle(depositTime);

                for (int index = 0; index < campaign.tiers().size(); index++) {
                    RedemptionDtos.TierResponse tier = campaign.tiers().get(index);
                    RedemptionDtos.CodeIssueResponse issue = codes.get(date + ":" + tier.id());
                    Cell codeCell = claimRow.createCell(index + 1);
                    Cell mergedBottomCell = depositRow.createCell(index + 1);
                    CellStyle cellStyle = issueStyle(issue, code, failed);
                    codeCell.setCellValue(safeText(codeValue(issue, importedCodes, codeIndex)));
                    codeCell.setCellStyle(cellStyle);
                    mergedBottomCell.setCellStyle(cellStyle);
                    sheet.addMergedRegion(new CellRangeAddress(rowIndex, rowIndex + 1, index + 1, index + 1));
                }
                rowIndex += 2;
            }
        }
        if (startRow == 0) sheet.createFreezePane(1, 4);
        sheet.setColumnWidth(0, 31 * 256);
        for (int column = 1; column <= lastColumn; column++) sheet.setColumnWidth(column, 30 * 256);
        return rowIndex;
    }

    /** Matches the compact daily recharge report template: market title, one header row, then one row per claim date. */
    private int writeDailyRechargeSheet(Sheet sheet, MarketSheet marketSheet, int startRow, CellStyle title,
                                        CellStyle header, CellStyle date, CellStyle code, CellStyle failed) {
        RedemptionDtos.CampaignResponse campaign = marketSheet.campaign();
        int lastColumn = campaign.tiers().size();
        Row titleRow = sheet.createRow(startRow);
        Row mergedTitleRow = sheet.createRow(startRow + 1);
        titleRow.setHeightInPoints(22);
        mergedTitleRow.setHeightInPoints(22);
        for (int column = 0; column <= lastColumn; column++) {
            titleRow.createCell(column).setCellStyle(title);
            mergedTitleRow.createCell(column).setCellStyle(title);
        }
        titleRow.getCell(0).setCellValue(safeText(dailyMarketTitle(marketSheet.sheetName())));
        sheet.addMergedRegion(new CellRangeAddress(startRow, startRow + 1, 0, lastColumn));

        Row headerRow = sheet.createRow(startRow + 2);
        Cell dateHeader = headerRow.createCell(0);
        dateHeader.setCellValue("日期");
        dateHeader.setCellStyle(header);
        for (int index = 0; index < campaign.tiers().size(); index++) {
            RedemptionDtos.TierResponse tier = campaign.tiers().get(index);
            Cell headerCell = headerRow.createCell(index + 1);
            headerCell.setCellValue("deposit" + plainAmount(tier.minDepositAmount()));
            headerCell.setCellStyle(header);
        }

        Map<String, RedemptionDtos.CodeIssueResponse> codes = issueMap(marketSheet.issues());
        Map<Long, List<String>> importedCodes = importedCodeMap(marketSheet.issues());
        int rowIndex = startRow + 3;
        for (LocalDate claimDate = marketSheet.from(); !claimDate.isAfter(marketSheet.to()); claimDate = claimDate.plusDays(1)) {
            int codeCount = codesOnDate(marketSheet.issues(), importedCodes, claimDate);
            for (int codeIndex = 0; codeIndex < codeCount; codeIndex++) {
                Row dataRow = sheet.createRow(rowIndex++);
                Cell dateCell = dataRow.createCell(0);
                dateCell.setCellValue(java.sql.Date.valueOf(claimDate));
                dateCell.setCellStyle(date);
                for (int index = 0; index < campaign.tiers().size(); index++) {
                    RedemptionDtos.TierResponse tier = campaign.tiers().get(index);
                    RedemptionDtos.CodeIssueResponse issue = codes.get(claimDate + ":" + tier.id());
                    Cell codeCell = dataRow.createCell(index + 1);
                    codeCell.setCellValue(safeText(codeValue(issue, importedCodes, codeIndex)));
                    codeCell.setCellStyle(issueStyle(issue, code, failed));
                }
            }
        }
        if (startRow == 0) sheet.createFreezePane(1, startRow + 3);
        sheet.setColumnWidth(0, 25 * 256);
        for (int column = 1; column <= lastColumn; column++) sheet.setColumnWidth(column, 13 * 256);
        return rowIndex;
    }

    private boolean isDailyRecharge(MarketSheet marketSheet) {
        return marketSheet.redemptionType() == RedemptionCodeType.PREVIOUS_DAY_DEPOSIT;
    }

    private boolean isAgent(MarketSheet marketSheet) {
        return marketSheet.redemptionType() == RedemptionCodeType.AGENT;
    }

    /**
     * Reproduces the two-column-per-tier agent template.  The combined sheet
     * keeps each market as a horizontal block, while individual market sheets
     * contain one such block.
     */
    private void writeAgentMultiMarketWorkbook(Workbook workbook, List<MarketSheet> marketSheets) {
        CellStyle title = agentTitleStyle(workbook);
        CellStyle header = agentHeaderStyle(workbook);
        CellStyle data = agentDataStyle(workbook);
        CellStyle failed = agentFailedStyle(workbook);
        Set<String> usedSheetNames = new HashSet<>();
        Sheet allMarkets = workbook.createSheet("全部盘口");
        usedSheetNames.add("全部盘口");
        int startColumn = 0;
        for (MarketSheet marketSheet : marketSheets) {
            Sheet sheet = workbook.createSheet(uniqueSheetName(marketSheet.sheetName(), usedSheetNames));
            writeAgentMarketBlock(sheet, marketSheet, 0, title, header, data, failed);
            sheet.createFreezePane(0, 2);
            startColumn = writeAgentMarketBlock(allMarkets, marketSheet, startColumn, title, header, data, failed) + 1;
        }
        allMarkets.createFreezePane(0, 2);
    }

    /** Returns the first blank column after the market's block. */
    private int writeAgentMarketBlock(Sheet sheet, MarketSheet marketSheet, int startColumn, CellStyle title,
                                      CellStyle header, CellStyle data, CellStyle failed) {
        RedemptionDtos.CampaignResponse campaign = marketSheet.campaign();
        int tierCount = campaign.tiers().size();
        int lastColumn = startColumn + Math.max(1, tierCount * 2) - 1;
        Row titleRow = row(sheet, 0);
        titleRow.setHeightInPoints(33);
        for (int column = startColumn; column <= lastColumn; column++) {
            Cell cell = cell(titleRow, column);
            cell.setCellStyle(title);
        }
        Cell titleCell = cell(titleRow, startColumn);
        titleCell.setCellValue(safeText(dailyMarketTitle(marketSheet.sheetName())));
        sheet.addMergedRegion(new CellRangeAddress(0, 0, startColumn, lastColumn));

        Row headerRow = row(sheet, 1);
        headerRow.setHeightInPoints(22);
        Map<String, RedemptionDtos.CodeIssueResponse> codes = issueMap(marketSheet.issues());
        Map<Long, List<String>> importedCodes = importedCodeMap(marketSheet.issues());
        for (int index = 0; index < tierCount; index++) {
            RedemptionDtos.TierResponse tier = campaign.tiers().get(index);
            int descriptionColumn = startColumn + index * 2;
            int codeColumn = descriptionColumn + 1;
            Cell descriptionHeader = cell(headerRow, descriptionColumn);
            descriptionHeader.setCellValue("兑换码组描述");
            descriptionHeader.setCellStyle(header);
            Cell codeHeader = cell(headerRow, codeColumn);
            codeHeader.setCellValue("兑换码号码");
            codeHeader.setCellStyle(header);
            sheet.setColumnWidth(descriptionColumn, agentDescriptionWidth(marketSheet, tier));
            sheet.setColumnWidth(codeColumn, 13 * 256);
        }

        int rowIndex = 2;
        for (LocalDate date = marketSheet.from(); !date.isAfter(marketSheet.to()); date = date.plusDays(1)) {
            int codeCount = codesOnDate(marketSheet.issues(), importedCodes, date);
            for (int codeIndex = 0; codeIndex < codeCount; codeIndex++) {
                Row dataRow = row(sheet, rowIndex++);
                dataRow.setHeightInPoints(21);
                for (int index = 0; index < tierCount; index++) {
                    RedemptionDtos.TierResponse tier = campaign.tiers().get(index);
                    RedemptionDtos.CodeIssueResponse issue = codes.get(date + ":" + tier.id());
                    int descriptionColumn = startColumn + index * 2;
                    Cell description = cell(dataRow, descriptionColumn);
                    description.setCellValue(safeText(agentDescription(marketSheet, issue)));
                    description.setCellStyle(issueStyle(issue, data, failed));
                    Cell code = cell(dataRow, descriptionColumn + 1);
                    code.setCellValue(safeText(codeValue(issue, importedCodes, codeIndex)));
                    code.setCellStyle(issueStyle(issue, data, failed));
                }
            }
        }
        return lastColumn + 1;
    }

    private String agentDescription(MarketSheet marketSheet, RedemptionDtos.CodeIssueResponse issue) {
        if (issue == null) return "";
        LocalDate effectiveDate = issue.claimDate().plusDays(marketSheet.effectiveFromDayOffset());
        String audience = issue.remoteLabelIds() == null || issue.remoteLabelIds().isEmpty()
                ? "全部"
                : "存款" + plainAmount(issue.minDepositAmount());
        return "%d-%02d代理%s".formatted(effectiveDate.getMonthValue(), effectiveDate.getDayOfMonth(), audience);
    }

    private int agentDescriptionWidth(MarketSheet marketSheet, RedemptionDtos.TierResponse tier) {
        boolean allUsers = marketSheet.issues().stream()
                .filter(issue -> issue.campaignTierId().equals(tier.id()))
                .findFirst()
                .map(issue -> issue.remoteLabelIds() == null || issue.remoteLabelIds().isEmpty())
                .orElse(false);
        return (allUsers ? 15 : 18) * 256;
    }

    private Row row(Sheet sheet, int rowIndex) {
        Row value = sheet.getRow(rowIndex);
        return value == null ? sheet.createRow(rowIndex) : value;
    }

    private Cell cell(Row row, int columnIndex) {
        Cell value = row.getCell(columnIndex);
        return value == null ? row.createCell(columnIndex) : value;
    }

    private Map<String, RedemptionDtos.CodeIssueResponse> issueMap(List<RedemptionDtos.CodeIssueResponse> issues) {
        Map<String, RedemptionDtos.CodeIssueResponse> codes = new HashMap<>();
        for (RedemptionDtos.CodeIssueResponse issue : issues) {
            codes.put(issue.claimDate() + ":" + issue.campaignTierId(), issue);
        }
        return codes;
    }

    private String dailyMarketTitle(String sheetName) {
        String value = sheetName == null ? "" : sheetName.trim();
        return value.replaceFirst("(?i)^raj", "").toLowerCase();
    }

    private String safeSheetName(String sheetName) {
        String requestedName = sheetName == null || sheetName.isBlank() ? DEFAULT_SHEET_NAME : sheetName.trim();
        return WorkbookUtil.createSafeSheetName(requestedName);
    }

    private String uniqueSheetName(String sheetName, Set<String> usedSheetNames) {
        String base = safeSheetName(sheetName);
        String candidate = base;
        for (int number = 2; usedSheetNames.contains(candidate); number++) {
            String suffix = " (" + number + ")";
            int prefixLength = Math.max(1, 31 - suffix.length());
            candidate = (base.length() > prefixLength ? base.substring(0, prefixLength) : base) + suffix;
        }
        usedSheetNames.add(candidate);
        return candidate;
    }

    private String depositHeaderText(RedemptionDtos.TierResponse tier) {
        return "Deposit:>" + plainAmount(tier.minDepositAmount());
    }

    private String dailyBonusText(int tierIndex, RedemptionDtos.TierResponse tier) {
        return tierIndex < PLAYER_DAILY_BONUSES.size() ? PLAYER_DAILY_BONUSES.get(tierIndex)
                : "Daily Bonus:₹" + bonusRange(tier.bonusAmount(), tier.bonusMaxAmount());
    }

    private String tierMessageText(int tierIndex, int lookbackDays, RedemptionDtos.TierResponse tier) {
        if (tierIndex < PLAYER_TIER_MESSAGES.size()) return PLAYER_TIER_MESSAGES.get(tierIndex);
        String minDeposit = plainAmount(tier.minDepositAmount());
        String totalBonus = currencyBonusRange(multiply(tier.bonusAmount(), lookbackDays), multiply(tier.bonusMaxAmount() == null ? tier.bonusAmount() : tier.bonusMaxAmount(), lookbackDays));
        return "Aaj ₹" + minDeposit + " deposit karo, aur"
                + "\naagle din se " + lookbackDays + " din tak free"
                + "\nbonus pao!"
                + "\n" + totalBonus;
    }

    private CellStyle issueStyle(RedemptionDtos.CodeIssueResponse issue, CellStyle code, CellStyle failed) {
        return issue != null && "FAILED".equals(issue.state()) ? failed : code;
    }

    private Map<Long, List<String>> importedCodeMap(List<RedemptionDtos.CodeIssueResponse> issues) {
        Map<Long, List<String>> result = new HashMap<>();
        issues.forEach(issue -> result.put(issue.id(), issue.redemptionCodes()));
        return result;
    }

    private int codesOnDate(List<RedemptionDtos.CodeIssueResponse> issues, Map<Long, List<String>> importedCodes, LocalDate date) {
        return Math.max(1, issues.stream().filter(issue -> issue.claimDate().equals(date))
                .mapToInt(issue -> importedCodes.get(issue.id()).size()).max().orElse(1));
    }

    private String codeValue(RedemptionDtos.CodeIssueResponse issue, Map<Long, List<String>> importedCodes, int codeIndex) {
        if (issue == null || "PENDING".equals(issue.state())) return "Pending";
        if ("FAILED".equals(issue.state())) return "Generation failed";
        List<String> codes = importedCodes.get(issue.id());
        if (codes.isEmpty()) return "Pending";
        return codeIndex < codes.size() ? codes.get(codeIndex) : "";
    }

    private CellStyle titleStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        Font font = workbook.createFont();
        font.setFontName("Times New Roman");
        font.setFontHeightInPoints((short) 12);
        style.setFont(font);
        borders(style);
        return style;
    }

    private CellStyle tierHeaderStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        style.setWrapText(true);
        Font font = workbook.createFont();
        font.setFontName("Times New Roman");
        font.setFontHeightInPoints((short) 10);
        style.setFont(font);
        borders(style);
        return style;
    }

    private CellStyle dateHeaderStyle(Workbook workbook) {
        CellStyle style = tierHeaderStyle(workbook);
        Font font = workbook.createFont();
        font.setFontName("Times New Roman");
        font.setFontHeightInPoints((short) 16);
        style.setFont(font);
        return style;
    }

    private CellStyle claimTimeStyle(Workbook workbook) {
        CellStyle style = baseDateStyle(workbook);
        style.setFillForegroundColor(IndexedColors.BRIGHT_GREEN.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        Font font = workbook.createFont();
        font.setFontName("Times New Roman");
        font.setBold(true);
        style.setFont(font);
        return style;
    }

    private CellStyle depositTimeStyle(Workbook workbook) {
        CellStyle style = baseDateStyle(workbook);
        Font font = workbook.createFont();
        font.setFontName("Times New Roman");
        style.setFont(font);
        return style;
    }

    private CellStyle baseDateStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        style.setWrapText(true);
        borders(style);
        return style;
    }

    private CellStyle codeStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        Font font = workbook.createFont();
        font.setFontName("Times New Roman");
        style.setFont(font);
        borders(style);
        return style;
    }

    private CellStyle failedStyle(Workbook workbook) {
        CellStyle style = codeStyle(workbook);
        style.setFillForegroundColor(IndexedColors.ROSE.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        return style;
    }

    private CellStyle dailyTitleStyle(Workbook workbook) {
        CellStyle style = dailyBaseStyle(workbook, (short) 22, true);
        style.setBorderTop(BorderStyle.NONE);
        style.setBorderRight(BorderStyle.NONE);
        style.setBorderBottom(BorderStyle.NONE);
        style.setBorderLeft(BorderStyle.NONE);
        style.setFillForegroundColor(IndexedColors.YELLOW.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        return style;
    }

    private CellStyle dailyHeaderStyle(Workbook workbook) {
        CellStyle style = dailyBaseStyle(workbook, (short) 11, true);
        // Accent 5 (#4BACC6) is the teal header color used by data/存款.xlsx's 报表 sheet.
        if (style instanceof XSSFCellStyle xssfStyle) {
            xssfStyle.setFillForegroundColor(new XSSFColor(new byte[] {0x4b, (byte) 0xac, (byte) 0xc6}));
        } else {
            style.setFillForegroundColor(IndexedColors.TURQUOISE.getIndex());
        }
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        return style;
    }

    private CellStyle dailyDateStyle(Workbook workbook) {
        CellStyle style = dailyBaseStyle(workbook, (short) 11, false);
        style.setDataFormat(workbook.createDataFormat().getFormat("m\"月\"d\"日\""));
        return style;
    }

    private CellStyle dailyCodeStyle(Workbook workbook) {
        return dailyBaseStyle(workbook, (short) 11, false);
    }

    private CellStyle dailyFailedStyle(Workbook workbook) {
        CellStyle style = dailyCodeStyle(workbook);
        style.setFillForegroundColor(IndexedColors.ROSE.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        return style;
    }

    private CellStyle agentTitleStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        Font font = workbook.createFont();
        font.setFontName("宋体");
        font.setFontHeightInPoints((short) 26);
        style.setFont(font);
        return style;
    }

    private CellStyle agentHeaderStyle(Workbook workbook) {
        CellStyle style = dailyBaseStyle(workbook, (short) 11, true);
        if (style instanceof XSSFCellStyle xssfStyle) {
            xssfStyle.setFillForegroundColor(new XSSFColor(new byte[] {0x4a, (byte) 0xc1, (byte) 0xff}));
        } else {
            style.setFillForegroundColor(IndexedColors.LIGHT_CORNFLOWER_BLUE.getIndex());
        }
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        return style;
    }

    private CellStyle agentDataStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setAlignment(HorizontalAlignment.LEFT);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        Font font = workbook.createFont();
        font.setFontName("宋体");
        font.setFontHeightInPoints((short) 11);
        style.setFont(font);
        borders(style);
        return style;
    }

    private CellStyle agentFailedStyle(Workbook workbook) {
        CellStyle style = agentDataStyle(workbook);
        style.setFillForegroundColor(IndexedColors.ROSE.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        return style;
    }

    private CellStyle dailyBaseStyle(Workbook workbook, short fontSize, boolean bold) {
        CellStyle style = workbook.createCellStyle();
        style.setAlignment(HorizontalAlignment.CENTER);
        style.setVerticalAlignment(VerticalAlignment.CENTER);
        Font font = workbook.createFont();
        font.setFontName("宋体");
        font.setFontHeightInPoints(fontSize);
        font.setBold(bold);
        style.setFont(font);
        borders(style);
        return style;
    }

    private void borders(CellStyle style) {
        style.setBorderTop(BorderStyle.THIN);
        style.setBorderRight(BorderStyle.THIN);
        style.setBorderBottom(BorderStyle.THIN);
        style.setBorderLeft(BorderStyle.THIN);
    }

    private String plainAmount(BigDecimal value) {
        return value == null ? "0" : value.stripTrailingZeros().toPlainString();
    }

    private BigDecimal multiply(BigDecimal value, int multiplier) {
        return (value == null ? BigDecimal.ZERO : value).multiply(BigDecimal.valueOf(multiplier));
    }

    private String bonusRange(BigDecimal min, BigDecimal max) {
        String minimum = plainAmount(min);
        String maximum = plainAmount(max == null ? min : max);
        return minimum.equals(maximum) ? minimum : minimum + "–" + maximum;
    }

    private String currencyBonusRange(BigDecimal min, BigDecimal max) {
        String minimum = plainAmount(min);
        String maximum = plainAmount(max == null ? min : max);
        return minimum.equals(maximum) ? "₹" + minimum : "₹" + minimum + " → ₹" + maximum;
    }

    static String safeText(String value) {
        if (value == null) return "";
        String trimmed = value.stripLeading();
        return !trimmed.isEmpty() && "=+-@".indexOf(trimmed.charAt(0)) >= 0 ? "'" + value : value;
    }
}
