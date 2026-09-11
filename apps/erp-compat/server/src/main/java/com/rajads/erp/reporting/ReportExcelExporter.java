package com.rajads.erp.reporting;

import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.CellStyle;
import org.apache.poi.ss.usermodel.FillPatternType;
import org.apache.poi.ss.usermodel.Font;
import org.apache.poi.ss.usermodel.HorizontalAlignment;
import org.apache.poi.ss.usermodel.IndexedColors;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.util.CellRangeAddress;
import org.apache.poi.ss.util.CellReference;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.stereotype.Component;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.math.BigDecimal;
import java.util.List;

@Component
public class ReportExcelExporter {
    private static final int MAX_EXCEL_TEXT_LENGTH = 32_767;
    private static final String[] HEADERS = {
            "期间", "币种", "期初余额", "转U", "欺诈损失（转账扣）", "有效转账", "消耗", "汇损", "服务费",
            "回流", "退款", "其他扣减", "欺诈损失（结余扣）", "期末余额", "记录数", "警告"
    };
    private static final int FIRST_NUMERIC_COLUMN = 2;
    private static final int LAST_NUMERIC_COLUMN = 14;

    public byte[] export(ReportDtos.ReportResponse report) {
        try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet("日报".equals(report.type()) || "DAILY".equals(report.type()) ? "日报汇总" : "月报汇总");
            CellStyle headerStyle = headerStyle(workbook);
            CellStyle amountStyle = amountStyle(workbook);
            CellStyle totalStyle = totalStyle(workbook, amountStyle);
            CellStyle wrappedStyle = wrappedStyle(workbook);

            Row header = sheet.createRow(0);
            for (int column = 0; column < HEADERS.length; column++) {
                Cell cell = header.createCell(column);
                cell.setCellValue(HEADERS[column]);
                cell.setCellStyle(headerStyle);
            }

            int rowIndex = 1;
            for (ReportDtos.ReportRow reportRow : report.rows()) {
                Row row = sheet.createRow(rowIndex++);
                text(row.createCell(0), reportRow.period());
                text(row.createCell(1), reportRow.asset());
                amount(row.createCell(2), reportRow.openingBalance(), amountStyle);
                amount(row.createCell(3), reportRow.transferAmount(), amountStyle);
                amount(row.createCell(4), reportRow.fraudFromTransfer(), amountStyle);
                amount(row.createCell(5), reportRow.effectiveTransferAmount(), amountStyle);
                amount(row.createCell(6), reportRow.spendAmount(), amountStyle);
                amount(row.createCell(7), reportRow.exchangeLossAmount(), amountStyle);
                amount(row.createCell(8), reportRow.serviceFeeAmount(), amountStyle);
                amount(row.createCell(9), reportRow.refluxAmount(), amountStyle);
                amount(row.createCell(10), reportRow.refundAmount(), amountStyle);
                amount(row.createCell(11), reportRow.otherDeductionAmount(), amountStyle);
                amount(row.createCell(12), reportRow.fraudFromBalance(), amountStyle);
                amount(row.createCell(13), reportRow.closingBalance(), amountStyle);
                amount(row.createCell(14), BigDecimal.valueOf(reportRow.recordCount()), amountStyle);
                Cell warnings = row.createCell(15);
                text(warnings, String.join("\n", reportRow.warnings()));
                warnings.setCellStyle(wrappedStyle);
            }

            Row total = sheet.createRow(rowIndex);
            Cell totalLabel = total.createCell(0);
            totalLabel.setCellValue("合计");
            totalLabel.setCellStyle(totalStyle);
            total.createCell(1).setCellStyle(totalStyle);
            for (int column = FIRST_NUMERIC_COLUMN; column <= LAST_NUMERIC_COLUMN; column++) {
                Cell cell = total.createCell(column);
                cell.setCellStyle(totalStyle);
                String formula = report.rows().isEmpty() ? "0" : "SUM(" + CellReference.convertNumToColString(column)
                        + "2:" + CellReference.convertNumToColString(column) + rowIndex + ")";
                cell.setCellFormula(formula);
            }
            total.createCell(15).setCellStyle(totalStyle);

            sheet.createFreezePane(0, 1);
            sheet.setAutoFilter(new CellRangeAddress(0, 0, 0, HEADERS.length - 1));
            for (int column = 0; column < HEADERS.length; column++) {
                sheet.setColumnWidth(column, column == 15 ? 38 * 256 : 16 * 256);
            }
            workbook.write(output);
            return output.toByteArray();
        } catch (IOException exception) {
            throw new IllegalStateException("无法生成报表 Excel", exception);
        }
    }

    private static CellStyle headerStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setFillForegroundColor(IndexedColors.DARK_BLUE.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        style.setAlignment(HorizontalAlignment.CENTER);
        Font font = workbook.createFont();
        font.setColor(IndexedColors.WHITE.getIndex());
        font.setBold(true);
        style.setFont(font);
        return style;
    }

    private static CellStyle amountStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setDataFormat(workbook.createDataFormat().getFormat("#,##0.00########"));
        return style;
    }

    private static CellStyle totalStyle(Workbook workbook, CellStyle amountStyle) {
        CellStyle style = workbook.createCellStyle();
        style.cloneStyleFrom(amountStyle);
        style.setFillForegroundColor(IndexedColors.LIGHT_CORNFLOWER_BLUE.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        Font font = workbook.createFont();
        font.setBold(true);
        style.setFont(font);
        return style;
    }

    private static CellStyle wrappedStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setWrapText(true);
        return style;
    }

    private static void amount(Cell cell, BigDecimal value, CellStyle style) {
        cell.setCellValue(value == null ? 0D : value.doubleValue());
        cell.setCellStyle(style);
    }

    private static void text(Cell cell, String value) {
        cell.setCellValue(safeText(value));
    }

    /** Excel treats these prefixes as formulas even when they came from a text field. */
    static String safeText(String value) {
        if (value == null) return "";
        String safe = isFormulaLike(value) ? "'" + value : value;
        return safe.length() <= MAX_EXCEL_TEXT_LENGTH ? safe : safe.substring(0, MAX_EXCEL_TEXT_LENGTH - 3) + "...";
    }

    private static boolean isFormulaLike(String value) {
        int index = 0;
        while (index < value.length() && Character.isWhitespace(value.charAt(index))) index++;
        return index < value.length() && "=+-@".indexOf(value.charAt(index)) >= 0;
    }
}
