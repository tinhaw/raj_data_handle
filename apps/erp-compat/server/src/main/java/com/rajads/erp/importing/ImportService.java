package com.rajads.erp.importing;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.audit.AuditService;
import com.rajads.erp.balance.BalanceDtos;
import com.rajads.erp.balance.BalanceService;
import com.rajads.erp.balance.DailyBalance;
import com.rajads.erp.balance.DailyBalanceRepository;
import com.rajads.erp.config.ErpProperties;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.identity.OperatorAccessService;
import com.rajads.erp.operator.Operator;
import com.rajads.erp.operator.OperatorAccount;
import com.rajads.erp.operator.OperatorAccountRepository;
import com.rajads.erp.operator.OperatorService;
import com.rajads.erp.shared.ApiException;
import com.rajads.erp.shared.DecimalUtils;
import lombok.RequiredArgsConstructor;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
public class ImportService {
    private static final Set<String> STRATEGIES = Set.of("SKIP_EXISTING", "UPDATE_DRAFT", "REJECT_ON_CONFLICT");
    private static final int MAX_EXCEL_TEXT_LENGTH = 32_767;
    private final ImportJobRepository jobRepository;
    private final ImportJobRowRepository rowRepository;
    private final DailyBalanceRepository balanceRepository;
    private final BalanceService balanceService;
    private final OperatorService operatorService;
    private final OperatorAccountRepository accountRepository;
    private final CurrentUser currentUser;
    private final OperatorAccessService operatorAccessService;
    private final AuditService auditService;
    private final ObjectMapper objectMapper;
    private final ErpProperties properties;

    @Transactional
    public ImportDtos.ImportPreviewResponse previewPaste(ImportDtos.PastePreviewRequest request) {
        requireActivePresetAccount(request.accountId());
        List<ParsedRow> parsed = parsePaste(request.text(), request.accountId());
        return persistPreview("PASTE", null, null, normalizeStrategy(request.conflictStrategy()), parsed);
    }

    @Transactional
    public ImportDtos.ImportPreviewResponse previewExcel(MultipartFile file, Long accountId, Integer businessYear, String conflictStrategy) {
        String filename = file.getOriginalFilename() == null ? "upload.xlsx" : file.getOriginalFilename();
        if (!filename.toLowerCase(Locale.ROOT).endsWith(".xlsx")) {
            throw ApiException.badRequest("IMPORT_FILE_TYPE_INVALID", "第一阶段仅支持 .xlsx 文件");
        }
        if (file.isEmpty()) throw ApiException.badRequest("IMPORT_FILE_EMPTY", "上传文件为空");
        requireActivePresetAccount(accountId);
        int selectedBusinessYear = normalizeBusinessYear(businessYear);
        try {
            byte[] content = file.getBytes();
            ParsedWorkbook parsed = parseWorkbook(content, accountId, selectedBusinessYear);
            if (jobRepository.existsByFileSha256AndStatus(sha256(content), "SUCCEEDED")
                    && (conflictStrategy == null || conflictStrategy.isBlank())) {
                throw ApiException.conflict("IMPORT_FILE_ALREADY_SUCCEEDED", "该文件已成功导入；如确认需要再次预览，请显式选择冲突策略");
            }
            ImportDtos.ImportPreviewResponse preview = persistPreview(parsed.sourceType(), filename, sha256(content),
                    normalizeStrategy(conflictStrategy), parsed.rows());
            Path sourcePath = sourcePath(preview.job().id());
            Files.createDirectories(sourcePath.getParent());
            Files.write(sourcePath, content);
            return preview;
        } catch (IOException exception) {
            throw ApiException.badRequest("IMPORT_FILE_READ_FAILED", "无法读取 Excel 文件");
        }
    }

    @Transactional(readOnly = true)
    public List<ImportDtos.ImportJobResponse> list() {
        Long userId = currentUser.require().id();
        if (operatorAccessService.hasAllOperators()) {
            return jobRepository.findAllByOrderByCreatedAtDesc().stream().map(this::jobResponse).toList();
        }
        Set<Long> accessibleOperatorIds = operatorAccessService.accessibleOperatorIds();
        return jobRepository.findByCreatedByOrderByCreatedAtDesc(userId).stream()
                .filter(job -> isWithinCurrentScope(job, accessibleOperatorIds))
                .map(this::jobResponse).toList();
    }

    @Transactional(readOnly = true)
    public XlsxDownload template() {
        return new XlsxDownload("daily-balance-import-template.xlsx", createStandardTemplate());
    }

    @Transactional(readOnly = true)
    public XlsxDownload source(Long jobId) {
        ImportJob job = requireJob(jobId);
        Path path = sourcePath(job.getId());
        if (!job.getSourceType().startsWith("XLSX") || !Files.isRegularFile(path)) {
            throw new ApiException(HttpStatus.NOT_FOUND, "IMPORT_SOURCE_NOT_AVAILABLE", "该导入批次没有可下载的原始文件");
        }
        try {
            return new XlsxDownload(downloadFilename(job.getOriginalFilename(), "import-" + job.getId() + ".xlsx"), Files.readAllBytes(path));
        } catch (IOException exception) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "IMPORT_SOURCE_READ_FAILED", "无法读取原始导入文件");
        }
    }

    @Transactional(readOnly = true)
    public XlsxDownload errorReport(Long jobId) {
        ImportJob job = requireJob(jobId);
        return new XlsxDownload("import-" + job.getId() + "-error-report.xlsx", createErrorReport(job));
    }

    @Transactional(readOnly = true)
    public ImportDtos.ImportPreviewResponse get(Long jobId) {
        ImportJob job = requireJob(jobId);
        return new ImportDtos.ImportPreviewResponse(jobResponse(job), rowsForJob(jobId));
    }

    @Transactional(readOnly = true)
    public List<ImportDtos.ImportRowResponse> rows(Long jobId) {
        requireJob(jobId);
        return rowsForJob(jobId);
    }

    @Transactional
    public ImportDtos.ImportCommitResponse commit(Long jobId, ImportDtos.ImportCommitRequest request) {
        ImportJob job = requireJob(jobId);
        if (!"PREVIEW_READY".equals(job.getStatus())) throw ApiException.conflict("IMPORT_JOB_NOT_READY", "该导入批次不能重复提交");
        if (job.getErrorRows() > 0) throw ApiException.badRequest("IMPORT_HAS_ERRORS", "导入预览仍有错误，请先修正数据");
        String strategy = normalizeStrategy(request == null ? job.getConflictStrategy() : request.conflictStrategy());
        int created = 0, updated = 0, skipped = 0;
        List<ImportJobRow> rows = rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(jobId);
        validateCommitRows(rows, strategy);
        for (ImportJobRow row : rows) {
            if (row.getNormalizedJson() == null) continue;
            BalanceDtos.DailyBalanceUpsertRequest command = deserialize(row.getNormalizedJson());
            Optional<DailyBalance> existing = balanceRepository.findByOperatorAccountIdAndBusinessDate(command.operatorAccountId(), command.businessDate());
            if ("DUPLICATE_IN_FILE".equals(row.getErrorCode())) {
                existing.ifPresent(balance -> row.setTargetDailyBalanceId(balance.getId()));
                row.setAction("SKIPPED"); skipped++;
            } else if (existing.isEmpty()) {
                BalanceDtos.DailyBalanceResponse saved = balanceService.createImported(command);
                row.setTargetDailyBalanceId(saved.id()); row.setAction("CREATED"); created++;
            } else if ("SKIP_EXISTING".equals(strategy)) {
                row.setTargetDailyBalanceId(existing.get().getId()); row.setAction("SKIPPED"); skipped++;
            } else if ("UPDATE_DRAFT".equals(strategy)) {
                assertUpdateDraftPreviewMatches(row, existing);
                balanceService.updateImported(existing.get().getId(), command, row.getPreviewRowVersion());
                row.setTargetDailyBalanceId(existing.get().getId()); row.setAction("UPDATED"); updated++;
            } else {
                throw ApiException.conflict("IMPORT_CONFLICT", "存在重复日结记录");
            }
            rowRepository.save(row);
        }
        job.setStatus("SUCCEEDED"); job.setConflictStrategy(strategy); job.setCommittedBy(currentUser.require().id()); job.setCommittedAt(java.time.Instant.now());
        jobRepository.save(job);
        auditService.record("IMPORT_COMMITTED", "IMPORT_JOB", jobId.toString(), null, null,
                Map.of("created", created, "updated", updated, "skipped", skipped, "sourceType", job.getSourceType()));
        return new ImportDtos.ImportCommitResponse(jobResponse(job), created, updated, skipped);
    }

    /** Validate all mutable targets before processing any rows, so an invalid or stale preview cannot partially apply. */
    private void validateCommitRows(List<ImportJobRow> rows, String strategy) {
        for (ImportJobRow row : rows) {
            if (row.getNormalizedJson() == null) continue;
            BalanceDtos.DailyBalanceUpsertRequest command = deserialize(row.getNormalizedJson());
            requireActiveImportAccount(operatorService.requireAccount(command.operatorAccountId()));
            if ("UPDATE_DRAFT".equals(strategy) && !"DUPLICATE_IN_FILE".equals(row.getErrorCode())) {
                Optional<DailyBalance> existing = balanceRepository.findByOperatorAccountIdAndBusinessDate(command.operatorAccountId(), command.businessDate());
                assertUpdateDraftPreviewMatches(row, existing);
            }
        }
    }

    private void assertUpdateDraftPreviewMatches(ImportJobRow row, Optional<DailyBalance> existing) {
        Long previewId = row.getPreviewDailyBalanceId();
        Long previewVersion = row.getPreviewRowVersion();
        if (previewId == null) {
            if (existing.isPresent()) throw stalePreview();
            return;
        }
        if (previewVersion == null || existing.isEmpty() || !Objects.equals(previewId, existing.get().getId())
                || !Objects.equals(previewVersion, existing.get().getRowVersion()) || !"DRAFT".equals(existing.get().getStatus())) {
            throw stalePreview();
        }
    }

    private ApiException stalePreview() {
        return ApiException.conflict("IMPORT_PREVIEW_STALE", "预检后目标草稿已变化，请重新预检后提交");
    }

    private ImportDtos.ImportPreviewResponse persistPreview(String sourceType, String filename, String hash, String strategy, List<ParsedRow> parsed) {
        ImportJob job = new ImportJob();
        job.setSourceType(sourceType); job.setOriginalFilename(filename); job.setFileSha256(hash); job.setStatus("PREVIEW_READY");
        job.setConflictStrategy(strategy); job.setCreatedBy(currentUser.require().id());
        job = jobRepository.save(job);
        int valid = 0, warning = 0, errors = 0;
        Set<String> keysInCurrentBatch = new HashSet<>();
        for (ParsedRow source : parsed) {
            ImportJobRow row = new ImportJobRow();
            row.setImportJobId(job.getId()); row.setSourceSheet(source.sheet()); row.setSourceRow(source.row());
            row.setSourceJson(source.raw()); row.setOperatorName(source.operatorName());
            if (source.errorCode() != null) {
                row.setSeverity("ERROR"); row.setErrorCode(source.errorCode()); row.setErrorMessage(source.errorMessage()); errors++;
            } else {
                row.setOperatorAccountId(source.command().operatorAccountId()); row.setBusinessDate(source.command().businessDate());
                row.setNormalizedJson(serialize(source.command()));
                String key = source.command().operatorAccountId() + "|" + source.command().businessDate();
                if (!keysInCurrentBatch.add(key)) {
                    row.setSeverity("WARNING"); row.setAction("SKIP"); row.setErrorCode("DUPLICATE_IN_FILE");
                    row.setErrorMessage("同一导入批次中存在相同投放线和日期，后续行默认跳过"); warning++;
                } else {
                    Optional<DailyBalance> existing = balanceRepository.findByOperatorAccountIdAndBusinessDate(source.command().operatorAccountId(), source.command().businessDate());
                    if (existing.isPresent()) {
                        row.setPreviewDailyBalanceId(existing.get().getId());
                        row.setPreviewRowVersion(existing.get().getRowVersion());
                        row.setSeverity("WARNING"); row.setAction("SKIP"); row.setErrorCode("DUPLICATE_RECORD"); row.setErrorMessage("系统中已有该投放线日期的记录，默认跳过"); warning++;
                    }
                    else { row.setSeverity("OK"); row.setAction("CREATE"); valid++; }
                }
            }
            rowRepository.save(row);
        }
        job.setTotalRows(parsed.size()); job.setValidRows(valid); job.setWarningRows(warning); job.setErrorRows(errors);
        jobRepository.save(job);
        // The caller just submitted these rows, so return the fresh preview directly.
        // Later history/detail reads use the current operator-scope check in requireJob.
        return new ImportDtos.ImportPreviewResponse(jobResponse(job), rowsForJob(job.getId()));
    }

    private byte[] createStandardTemplate() {
        String[] headers = {"业务日期", "投放公司", "投放线", "币种", "期初余额", "转U", "欺诈损失", "欺诈承担方", "消耗",
                "汇损费率", "汇损基数", "汇损模式", "汇损金额", "汇损原因", "服务费率", "服务费基数", "服务费模式",
                "服务费金额", "服务费原因", "回流", "退款", "其他扣减", "其他原因", "备注"};
        try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            CellStyle headerStyle = exportHeaderStyle(workbook);
            Sheet data = workbook.createSheet("导入数据");
            Row header = data.createRow(0);
            for (int index = 0; index < headers.length; index++) {
                Cell cell = header.createCell(index);
                cell.setCellValue(headers[index]);
                cell.setCellStyle(headerStyle);
                data.setColumnWidth(index, 16 * 256);
            }
            data.createFreezePane(0, 1);
            data.setAutoFilter(new org.apache.poi.ss.util.CellRangeAddress(0, 0, 0, headers.length - 1));

            Sheet notes = workbook.createSheet("填写说明");
            String[] instructions = {
                    "请在“导入数据”工作表从第 2 行开始填入数据；不要修改表头。",
                    "业务日期格式：yyyy-MM-dd。投放公司可填名称（兼容历史编码）；投放线可填名称（兼容历史编码）。",
                    "如上传时已选择投放线，可省略投放公司、投放线和币种列；如仍提供，必须与所选投放线完全一致。",
                    "期初余额为空时，系统会按前一日自动带入；没有历史记录时请填写期初余额。",
                    "汇损费率、服务费率可填写 0.02 或 2%；手工金额请同时将基数或模式填为 MANUAL。",
                    "欺诈承担方可填 TRANSFER（从转账扣）或 BALANCE（从结余扣）。其他扣减金额不为 0 时必须填写其他原因。",
                    "有效转U、期末余额/本月结余均由系统计算，不得作为导入字段。空单元格表示未提供：UPDATE_DRAFT 不会覆盖已有值。"
            };
            for (int index = 0; index < instructions.length; index++) text(notes.createRow(index).createCell(0), instructions[index]);
            notes.setColumnWidth(0, 110 * 256);
            workbook.write(output);
            return output.toByteArray();
        } catch (IOException exception) {
            throw new IllegalStateException("无法生成导入模板", exception);
        }
    }

    private byte[] createErrorReport(ImportJob job) {
        String[] headers = {"来源工作表", "来源行", "投放公司", "投放线 ID", "业务日期", "严重级别", "错误代码", "错误信息", "处理动作", "原始数据"};
        List<ImportJobRow> issues = rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(job.getId()).stream()
                .filter(row -> !"OK".equals(row.getSeverity())).toList();
        try (Workbook workbook = new XSSFWorkbook(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet("异常行");
            CellStyle headerStyle = exportHeaderStyle(workbook);
            Row header = sheet.createRow(0);
            for (int index = 0; index < headers.length; index++) {
                Cell cell = header.createCell(index);
                cell.setCellValue(headers[index]);
                cell.setCellStyle(headerStyle);
                sheet.setColumnWidth(index, index == 9 ? 42 * 256 : 18 * 256);
            }
            int rowIndex = 1;
            for (ImportJobRow issue : issues) {
                Row row = sheet.createRow(rowIndex++);
                text(row.createCell(0), issue.getSourceSheet());
                integer(row.createCell(1), issue.getSourceRow());
                text(row.createCell(2), issue.getOperatorName());
                integer(row.createCell(3), issue.getOperatorAccountId());
                text(row.createCell(4), issue.getBusinessDate() == null ? null : issue.getBusinessDate().toString());
                text(row.createCell(5), issue.getSeverity());
                text(row.createCell(6), issue.getErrorCode());
                text(row.createCell(7), issue.getErrorMessage());
                text(row.createCell(8), issue.getAction());
                text(row.createCell(9), issue.getSourceJson());
            }
            sheet.createFreezePane(0, 1);
            sheet.setAutoFilter(new org.apache.poi.ss.util.CellRangeAddress(0, 0, 0, headers.length - 1));
            workbook.write(output);
            return output.toByteArray();
        } catch (IOException exception) {
            throw new IllegalStateException("无法生成导入错误报告", exception);
        }
    }

    private CellStyle exportHeaderStyle(Workbook workbook) {
        CellStyle style = workbook.createCellStyle();
        style.setFillForegroundColor(IndexedColors.DARK_BLUE.getIndex());
        style.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        Font font = workbook.createFont();
        font.setColor(IndexedColors.WHITE.getIndex());
        font.setBold(true);
        style.setFont(font);
        return style;
    }

    private void text(Cell cell, String value) {
        cell.setCellValue(safeExcelText(value));
    }

    private void integer(Cell cell, Number value) {
        if (value != null) cell.setCellValue(value.doubleValue());
    }

    private String safeExcelText(String value) {
        if (value == null) return "";
        int index = 0;
        while (index < value.length() && Character.isWhitespace(value.charAt(index))) index++;
        String safe = index < value.length() && "=+-@".indexOf(value.charAt(index)) >= 0 ? "'" + value : value;
        return safe.length() <= MAX_EXCEL_TEXT_LENGTH ? safe : safe.substring(0, MAX_EXCEL_TEXT_LENGTH - 3) + "...";
    }

    private Path sourcePath(Long jobId) {
        return Path.of(properties.storage().localPath(), "imports", "import-" + jobId + ".xlsx");
    }

    private String downloadFilename(String value, String fallback) {
        if (value == null || value.isBlank()) return fallback;
        String sanitized = value.replaceAll("[\\r\\n\\\\/]", "_").replaceAll("[\\p{Cntrl}]", "").trim();
        return sanitized.isBlank() ? fallback : sanitized;
    }

    private List<ParsedRow> parsePaste(String text, Long accountId) {
        String[] lines = text.replace("\r\n", "\n").replace('\r', '\n').split("\n");
        List<String[]> matrix = Arrays.stream(lines).map(line -> line.split("\t", -1)).filter(cells -> Arrays.stream(cells).anyMatch(value -> !value.isBlank())).toList();
        if (matrix.isEmpty()) return List.of(error("粘贴", 1, null, "IMPORT_EMPTY", "没有可导入的数据", text));
        Map<String, Integer> headers = headerMap(Arrays.asList(matrix.getFirst()));
        int start = 0;
        if (headers.containsKey("DATE")) start = 1;
        else headers = positionalHeaders();
        List<ParsedRow> result = new ArrayList<>();
        for (int i = start; i < matrix.size(); i++) {
            Map<String, String> values = values(headers, matrix.get(i));
            result.add(parseCommand("粘贴", i + 1, values, accountId, null, String.join("\t", matrix.get(i)), null));
        }
        return result;
    }

    private ParsedWorkbook parseWorkbook(byte[] data, Long presetAccountId, int businessYear) {
        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(data))) {
            FormulaEvaluator evaluator = workbook.getCreationHelper().createFormulaEvaluator();
            List<ParsedRow> parsed = new ArrayList<>(); boolean legacy = false;
            for (int s = 0; s < workbook.getNumberOfSheets(); s++) {
                Sheet sheet = workbook.getSheetAt(s);
                List<Integer> legacyHeaders = legacyHeaderRows(sheet, evaluator);
                if (!legacyHeaders.isEmpty()) {
                    for (Integer headerRow : legacyHeaders) {
                        parsed.addAll(parseLegacyBlock(sheet, headerRow, legacyBlockHeaders(sheet.getRow(headerRow), evaluator), presetAccountId, evaluator, businessYear));
                    }
                    legacy = true;
                    continue;
                }
                for (int r = 0; r <= Math.min(sheet.getLastRowNum(), 50); r++) {
                    Row headerRow = sheet.getRow(r); if (headerRow == null) continue;
                    Map<String, Integer> headers = headerMap(headerRow, evaluator);
                    if (headers.containsKey("DATE") && (headers.containsKey("ACCOUNT") || headers.containsKey("OPERATOR") || presetAccountId != null)) {
                        parsed.addAll(parseStandardSheet(sheet, r, headers, presetAccountId, evaluator, businessYear));
                        break;
                    }
                }
            }
            if (parsed.isEmpty()) parsed.add(error("Excel", 1, null, "IMPORT_TEMPLATE_UNRECOGNIZED", "未识别到标准行式或旧版分块表头", ""));
            if (parsed.size() > properties.importSettings().maxRows()) throw ApiException.badRequest("IMPORT_TOO_MANY_ROWS", "导入行数超过限制");
            return new ParsedWorkbook(legacy ? "XLSX_LEGACY" : "XLSX_STANDARD", parsed);
        } catch (IOException exception) {
            throw ApiException.badRequest("IMPORT_XLSX_INVALID", "Excel 文件格式不正确或无法解析");
        }
    }

    private List<ParsedRow> parseStandardSheet(Sheet sheet, int headerIndex, Map<String, Integer> headers, Long accountId, FormulaEvaluator evaluator, int businessYear) {
        List<ParsedRow> rows = new ArrayList<>(); int blankRows = 0;
        for (int r = headerIndex + 1; r <= sheet.getLastRowNum(); r++) {
            Row row = sheet.getRow(r); Map<String, String> values = values(headers, row, evaluator, businessYear);
            if (values.values().stream().allMatch(value -> value == null || value.isBlank())) { if (++blankRows >= 2) break; continue; }
            blankRows = 0;
            rows.add(parseCommand(sheet.getSheetName(), r + 1, values, accountId, null, serialize(values), businessYear));
        }
        return rows;
    }

    private List<ParsedRow> parseLegacyBlock(Sheet sheet, int headerIndex, Map<String, Integer> headers, Long presetAccountId, FormulaEvaluator evaluator, int businessYear) {
        List<ParsedRow> rows = new ArrayList<>();
        int openingColumn = headers.get("OPENING"); int dateColumn = openingColumn - 1;
        String operatorName = cellText(sheet.getRow(headerIndex).getCell(dateColumn), evaluator);
        BigDecimal firstOpening = decimalCell(sheet.getRow(headerIndex + 1), openingColumn, evaluator);
        BigDecimal exchangeRate = rateFromHeader(sheet.getRow(headerIndex).getCell(headers.get("EXCHANGE_AMOUNT")), evaluator);
        BigDecimal serviceRate = rateFromHeader(sheet.getRow(headerIndex).getCell(headers.get("SERVICE_AMOUNT")), evaluator);
        for (int r = headerIndex + 2; r <= sheet.getLastRowNum(); r++) {
            Row row = sheet.getRow(r); if (row == null) continue;
            LocalDate date = dateCell(row.getCell(dateColumn), evaluator, businessYear);
            if (date == null) {
                if (r > headerIndex + 3) break;
                continue;
            }
            Map<String, String> values = values(headers, row, evaluator, businessYear); values.put("OPERATOR", operatorName);
            values.put("DATE", date.toString());
            if (r == headerIndex + 2 && firstOpening != null) values.put("OPENING", firstOpening.toPlainString());
            BigDecimal exchangeAmount = decimalCell(row, headers.get("EXCHANGE_AMOUNT"), evaluator);
            values.put("EXCHANGE_RATE", exchangeRate == null ? "0" : exchangeRate.toPlainString());
            values.put("EXCHANGE_BASIS", "MANUAL"); values.put("EXCHANGE_MODE", "MANUAL");
            values.put("EXCHANGE_AMOUNT", (exchangeAmount == null ? BigDecimal.ZERO : exchangeAmount).toPlainString());
            BigDecimal spend = decimal(values.get("SPEND")); BigDecimal serviceAmount = decimalCell(row, headers.get("SERVICE_AMOUNT"), evaluator);
            if (serviceRate != null && serviceAmount != null && spend != null && serviceAmount.compareTo(spend.multiply(serviceRate).setScale(2, RoundingMode.HALF_UP)) == 0) {
                values.put("SERVICE_RATE", serviceRate.toPlainString()); values.put("SERVICE_BASIS", "SPEND"); values.put("SERVICE_MODE", "AUTO");
            } else {
                values.put("SERVICE_RATE", serviceRate == null ? "0" : serviceRate.toPlainString()); values.put("SERVICE_BASIS", "MANUAL"); values.put("SERVICE_MODE", "MANUAL");
                values.put("SERVICE_AMOUNT", (serviceAmount == null ? BigDecimal.ZERO : serviceAmount).toPlainString());
            }
            rows.add(parseCommand(sheet.getSheetName(), r + 1, values, presetAccountId, operatorName, serialize(values), businessYear));
        }
        return rows;
    }

    private ParsedRow parseCommand(String sheet, int row, Map<String, String> values, Long presetAccountId, String legacyOperator, String raw, Integer businessYear) {
        try {
            rejectComputedFields(values);
            LocalDate date = parseDate(required(values, "DATE", "缺少日期"), businessYear);
            OperatorAccount account = resolveAccount(values, presetAccountId);
            BigDecimal opening = decimal(values.get("OPENING"));
            BigDecimal transfer = decimal(values.get("TRANSFER"));
            BigDecimal fraud = decimal(values.get("FRAUD"));
            String fraudSource = fraudSource(values.get("FRAUD_SOURCE"));
            BigDecimal spend = decimal(values.get("SPEND"));
            BigDecimal exchangeAmount = decimal(values.get("EXCHANGE_AMOUNT"));
            BigDecimal serviceAmount = decimal(values.get("SERVICE_AMOUNT"));
            String exchangeBasis = first(values.get("EXCHANGE_BASIS"), exchangeAmount == null ? null : "TRANSFER");
            String exchangeMode = first(values.get("EXCHANGE_MODE"), exchangeAmount == null ? null : "MANUAL");
            String serviceBasis = first(values.get("SERVICE_BASIS"), serviceAmount == null ? null : "SPEND");
            String serviceMode = first(values.get("SERVICE_MODE"), serviceAmount == null ? null : "MANUAL");
            BigDecimal exchangeRate = rate(values.get("EXCHANGE_RATE"));
            BigDecimal serviceRate = rate(values.get("SERVICE_RATE"));
            BigDecimal reflux = decimal(values.get("REFLUX"));
            BigDecimal refund = decimal(values.get("REFUND"));
            BigDecimal other = decimal(values.get("OTHER"));
            String otherReason = trimToNull(values.get("OTHER_REASON"));
            // The compact grid deliberately omits these columns.  Populate import-only defaults so the normal
            // BalanceService integrity checks remain authoritative for all other APIs and source types.
            if (fraud != null && fraud.signum() > 0 && fraudSource == null) fraudSource = "TRANSFER";
            if (other != null && other.signum() > 0 && otherReason == null) otherReason = "批量导入";
            String exchangeReason = trimToNull(values.get("EXCHANGE_REASON"));
            String serviceReason = trimToNull(values.get("SERVICE_REASON"));
            validateImportRules(transfer, fraud, fraudSource, spend, exchangeRate, exchangeBasis, exchangeMode, exchangeAmount,
                    serviceRate, serviceBasis, serviceMode, serviceAmount, reflux, refund, other, otherReason);
            BalanceDtos.DailyBalanceUpsertRequest command = new BalanceDtos.DailyBalanceUpsertRequest(
                    account.getId(), date, opening, opening == null ? null : "MANUAL", null,
                    transfer, fraud, fraudSource, spend,
                    exchangeRate, exchangeBasis, exchangeMode, exchangeAmount, exchangeReason,
                    serviceRate, serviceBasis, serviceMode, serviceAmount, serviceReason,
                    reflux, refund, other, otherReason,
                    null, "IMPORT", trimToNull(values.get("REMARK")), null);
            return new ParsedRow(sheet, row, legacyOperator == null ? values.get("OPERATOR") : legacyOperator, command, null, null, raw);
        } catch (ApiException exception) {
            return error(sheet, row, legacyOperator == null ? values.get("OPERATOR") : legacyOperator, exception.getCode(), exception.getMessage(), raw);
        } catch (RuntimeException exception) {
            return error(sheet, row, legacyOperator == null ? values.get("OPERATOR") : legacyOperator, "IMPORT_ROW_INVALID", "导入行格式不正确", raw);
        }
    }

    private OperatorAccount resolveAccount(Map<String, String> values, Long presetAccountId) {
        if (presetAccountId != null) {
            OperatorAccount account = requireActivePresetAccount(presetAccountId);
            validatePresetAccountIdentity(values, account);
            return account;
        }
        String operatorValue = values.get("OPERATOR");
        if (operatorValue == null || operatorValue.isBlank()) throw ApiException.badRequest("IMPORT_OPERATOR_REQUIRED", "缺少投放公司；请先选择投放线或提供投放公司列");
        Operator operator = operatorService.findAccessibleOperatorByCodeOrName(operatorValue.trim())
                .or(() -> operatorService.findAccessibleOperatorByCodeOrName(operatorValue.replace("投放名字", "").trim()))
                .orElseThrow(() -> ApiException.badRequest("IMPORT_OPERATOR_NOT_FOUND", "未找到投放公司：" + operatorValue));
        List<OperatorAccount> accounts = accountRepository.findByOperatorIdAndStatus(operator.getId(), "ACTIVE");
        String accountValue = values.get("ACCOUNT");
        if (accountValue != null && !accountValue.isBlank()) accounts = accounts.stream().filter(account -> account.getCode().equalsIgnoreCase(accountValue.trim()) || account.getName().equalsIgnoreCase(accountValue.trim())).toList();
        String asset = values.get("ASSET");
        if (asset != null && !asset.isBlank()) accounts = accounts.stream().filter(account -> account.getAsset().equalsIgnoreCase(asset.trim())).toList();
        if (accounts.size() != 1) throw ApiException.badRequest("IMPORT_ACCOUNT_MAPPING_REQUIRED", "投放公司 " + operatorValue + " 无法唯一映射投放线");
        return requireActiveImportAccount(accounts.getFirst());
    }

    /** Fixed-line imports may include identity columns for legacy compatibility, but they must never be ignored. */
    private void validatePresetAccountIdentity(Map<String, String> values, OperatorAccount account) {
        String operatorValue = trimToNull(values.get("OPERATOR"));
        if (operatorValue != null) {
            Optional<Operator> operator = operatorService.findAccessibleOperatorByCodeOrName(operatorValue)
                    .or(() -> operatorService.findAccessibleOperatorByCodeOrName(operatorValue.replace("投放名字", "").trim()));
            if (operator.isEmpty() || !Objects.equals(operator.get().getId(), account.getOperatorId())) {
                throw ApiException.badRequest("IMPORT_PRESET_ACCOUNT_MISMATCH", "固定投放线与行内投放公司不一致");
            }
        }
        String accountValue = trimToNull(values.get("ACCOUNT"));
        if (accountValue != null && !accountValue.equalsIgnoreCase(account.getCode()) && !accountValue.equalsIgnoreCase(account.getName())) {
            throw ApiException.badRequest("IMPORT_PRESET_ACCOUNT_MISMATCH", "固定投放线与行内投放线不一致");
        }
        String asset = trimToNull(values.get("ASSET"));
        if (asset != null && !asset.equalsIgnoreCase(account.getAsset())) {
            throw ApiException.badRequest("IMPORT_PRESET_ACCOUNT_MISMATCH", "固定投放线与行内币种不一致");
        }
    }

    private OperatorAccount requireActivePresetAccount(Long accountId) {
        return accountId == null ? null : requireActiveImportAccount(operatorService.requireAccount(accountId));
    }

    private OperatorAccount requireActiveImportAccount(OperatorAccount account) {
        if (!"ACTIVE".equals(account.getStatus())) {
            throw ApiException.badRequest("IMPORT_ACCOUNT_INACTIVE", "投放线已停用，不能导入");
        }
        return account;
    }

    private void rejectComputedFields(Map<String, String> values) {
        if (trimToNull(values.get("EFFECTIVE_TRANSFER")) != null || trimToNull(values.get("CLOSING_BALANCE")) != null) {
            throw ApiException.badRequest("IMPORT_COMPUTED_FIELD_FORBIDDEN", "有效转U和期末余额由系统计算，不能导入");
        }
    }

    private void validateImportRules(BigDecimal transfer, BigDecimal fraud, String fraudSource, BigDecimal spend,
                                     BigDecimal exchangeRate, String exchangeBasis, String exchangeMode, BigDecimal exchangeAmount,
                                     BigDecimal serviceRate, String serviceBasis, String serviceMode,
                                     BigDecimal serviceAmount, BigDecimal reflux, BigDecimal refund,
                                     BigDecimal other, String otherReason) {
        for (AmountValue value : List.of(new AmountValue("转U", transfer), new AmountValue("欺诈损失", fraud),
                new AmountValue("消耗", spend), new AmountValue("汇损金额", exchangeAmount), new AmountValue("服务费金额", serviceAmount),
                new AmountValue("回流", reflux), new AmountValue("退款", refund), new AmountValue("其他扣减", other))) {
            DecimalUtils.requireNonNegative(value.label(), value.amount());
        }
        validateRate("汇损费率", exchangeRate);
        validateRate("服务费率", serviceRate);
        if (fraud != null && fraud.signum() > 0) {
            if (fraudSource == null || fraudSource.isBlank()) {
                throw ApiException.badRequest("FRAUD_SOURCE_REQUIRED", "欺诈损失不为 0 时必须选择承担方式");
            }
            if (!Set.of("TRANSFER", "BALANCE").contains(fraudSource)) {
                throw ApiException.badRequest("INVALID_FRAUD_SOURCE", "欺诈承担方式必须为 TRANSFER 或 BALANCE");
            }
            if ("TRANSFER".equals(fraudSource) && transfer != null && fraud.compareTo(transfer) > 0) {
                throw ApiException.badRequest("FRAUD_EXCEEDS_TRANSFER", "从转账扣除的欺诈损失不能大于转U");
            }
        }
        if (other != null && other.signum() > 0 && trimToNull(otherReason) == null) {
            throw ApiException.badRequest("OTHER_REASON_REQUIRED", "其他扣减金额不为 0 时必须填写原因");
        }
        validateManualFee(exchangeBasis, exchangeMode, exchangeAmount, "汇损");
        validateManualFee(serviceBasis, serviceMode, serviceAmount, "服务费");
    }

    private void validateRate(String label, BigDecimal rate) {
        if (rate != null && rate.compareTo(BigDecimal.ONE) > 0) {
            throw ApiException.badRequest("INVALID_RATE", label + "不得大于 1；2% 请传 0.02");
        }
    }

    private void validateManualFee(String basis, String mode, BigDecimal amount, String label) {
        if (!isManual(basis, mode)) return;
        DecimalUtils.requireNonNegative(label + "金额", amount);
        if (!currentUser.require().permissions().contains("BALANCE_OVERRIDE")) {
            throw ApiException.forbidden("没有手工覆盖自动金额的权限");
        }
    }

    private boolean isManual(String basis, String mode) {
        return "MANUAL".equalsIgnoreCase(trimToNull(basis)) || "MANUAL".equalsIgnoreCase(trimToNull(mode));
    }

    private record AmountValue(String label, BigDecimal amount) { }

    private Map<String, Integer> headerMap(Row row, FormulaEvaluator evaluator) {
        Map<String, Integer> result = new LinkedHashMap<>();
        if (row == null) return result;
        for (Cell cell : row) { String key = canonicalHeader(cellText(cell, evaluator)); if (key != null) result.putIfAbsent(key, cell.getColumnIndex()); }
        return result;
    }
    private Map<String, Integer> headerMap(List<String> cells) {
        Map<String, Integer> result = new LinkedHashMap<>();
        for (int i = 0; i < cells.size(); i++) { String key = canonicalHeader(cells.get(i)); if (key != null) result.putIfAbsent(key, i); }
        return result;
    }
    private Map<String, Integer> positionalHeaders() {
        String[] names = {"DATE", "OPENING", "TRANSFER", "SPEND", "EXCHANGE_RATE", "EXCHANGE_AMOUNT", "SERVICE_RATE", "SERVICE_AMOUNT", "REFLUX", "REFUND", "OTHER", "FRAUD", "FRAUD_SOURCE", "REMARK"};
        Map<String, Integer> result = new LinkedHashMap<>(); for (int i = 0; i < names.length; i++) result.put(names[i], i); return result;
    }
    private String canonicalHeader(String value) {
        if (value == null) return null; String s = value.replaceAll("[\\s_－—-]", "").toUpperCase(Locale.ROOT);
        if (s.equals("日期") || s.equals("业务日期") || s.equals("DATE")) return "DATE";
        if (s.contains("投放公司") || s.contains("运营方") || s.equals("投放名字") || s.equals("OPERATOR")) return "OPERATOR";
        if (s.contains("投放线") || s.contains("结算账户") || s.equals("账户") || s.equals("ACCOUNT")) return "ACCOUNT";
        if (s.equals("币种") || s.equals("ASSET")) return "ASSET";
        if (s.contains("昨日结余") || s.contains("期初")) return "OPENING";
        if (s.equals("有效转U") || s.equals("有效转账") || s.equals("EFFECTIVETRANSFER")) return "EFFECTIVE_TRANSFER";
        if (s.contains("期末余额") || s.contains("期末结余") || s.contains("本月结余") || s.contains("当日结余")
                || s.equals("结余") || s.equals("CLOSING") || s.equals("CLOSINGBALANCE")) return "CLOSING_BALANCE";
        if (s.equals("转U") || s.equals("转USDT") || s.equals("TRANSFER")) return "TRANSFER";
        if (s.contains("消耗") || s.equals("SPEND")) return "SPEND";
        if (s.contains("汇损") && (s.contains("费率") || s.endsWith("率") || s.contains("比例"))) return "EXCHANGE_RATE";
        if (s.contains("汇损") && s.contains("基数")) return "EXCHANGE_BASIS";
        if (s.contains("汇损") && s.contains("模式")) return "EXCHANGE_MODE";
        if (s.contains("汇损") && s.contains("原因")) return "EXCHANGE_REASON";
        if (s.contains("汇损")) return "EXCHANGE_AMOUNT";
        if (s.contains("服务费") && s.contains("费率")) return "SERVICE_RATE";
        if (s.contains("服务费") && s.contains("基数")) return "SERVICE_BASIS";
        if (s.contains("服务费") && s.contains("模式")) return "SERVICE_MODE";
        if (s.contains("服务费") && s.contains("原因")) return "SERVICE_REASON";
        if (s.contains("服务费")) return "SERVICE_AMOUNT";
        if (s.equals("回流")) return "REFLUX"; if (s.equals("退款")) return "REFUND";
        if (s.equals("其他") || s.contains("其他扣减")) return "OTHER"; if (s.contains("其他原因")) return "OTHER_REASON";
        if (s.contains("欺诈") && s.contains("承担")) return "FRAUD_SOURCE"; if (s.contains("欺诈")) return "FRAUD";
        if (s.equals("备注") || s.equals("REMARK")) return "REMARK";
        return null;
    }
    private Map<String, String> values(Map<String, Integer> headers, Row row, FormulaEvaluator evaluator, Integer businessYear) {
        Map<String, String> result = new HashMap<>(); for (var header : headers.entrySet()) { Cell cell = row == null ? null : row.getCell(header.getValue()); result.put(header.getKey(), header.getKey().equals("DATE") ? dateText(cell, evaluator, businessYear) : cellText(cell, evaluator)); } return result;
    }
    private boolean isLegacyHeader(Row row, FormulaEvaluator evaluator, Map<String, Integer> headers) {
        if (!headers.containsKey("OPENING") || !headers.containsKey("TRANSFER") || !headers.containsKey("SPEND")) return false;
        int opening = headers.get("OPENING");
        if (opening < 1 || headers.get("TRANSFER") != opening + 1 || headers.get("SPEND") != opening + 2) return false;
        String openingText = cellText(row.getCell(opening), evaluator);
        String transferText = cellText(row.getCell(opening + 1), evaluator);
        String spendText = cellText(row.getCell(opening + 2), evaluator);
        return openingText != null && openingText.contains("昨日结余")
                && transferText != null && transferText.replaceAll("\\s", "").equalsIgnoreCase("转U")
                && spendText != null && spendText.contains("消耗")
                && cellText(row.getCell(opening - 1), evaluator) != null;
    }
    private List<Integer> legacyHeaderRows(Sheet sheet, FormulaEvaluator evaluator) {
        List<Integer> result = new ArrayList<>();
        for (int r = 0; r <= Math.min(sheet.getLastRowNum(), 100); r++) {
            Row row = sheet.getRow(r); if (row == null) continue;
            for (int c = 1; c < row.getLastCellNum() - 2; c++) {
                String opening = cellText(row.getCell(c), evaluator);
                String transfer = cellText(row.getCell(c + 1), evaluator);
                String spend = cellText(row.getCell(c + 2), evaluator);
                if (opening != null && opening.replaceAll("\\s", "").equals("昨日结余")
                        && transfer != null && transfer.replaceAll("\\s", "").equalsIgnoreCase("转U")
                        && spend != null && spend.contains("消耗")
                        && cellText(row.getCell(c - 1), evaluator) != null) {
                    result.add(r);
                    break;
                }
            }
        }
        return result;
    }
    private Map<String, Integer> legacyBlockHeaders(Row row, FormulaEvaluator evaluator) {
        Map<String, Integer> headers = new LinkedHashMap<>();
        for (int c = 1; c < row.getLastCellNum() - 2; c++) {
            String opening = cellText(row.getCell(c), evaluator);
            String transfer = cellText(row.getCell(c + 1), evaluator);
            String spend = cellText(row.getCell(c + 2), evaluator);
            if (opening != null && opening.replaceAll("\\s", "").equals("昨日结余")
                    && transfer != null && transfer.replaceAll("\\s", "").equalsIgnoreCase("转U")
                    && spend != null && spend.contains("消耗")) {
                headers.put("OPENING", c); headers.put("TRANSFER", c + 1); headers.put("SPEND", c + 2);
                headers.put("EXCHANGE_AMOUNT", c + 3); headers.put("SERVICE_AMOUNT", c + 4);
                headers.put("REFLUX", c + 5); headers.put("REFUND", c + 6); headers.put("OTHER", c + 7);
                return headers;
            }
        }
        return headerMap(row, evaluator);
    }
    private Map<String, String> values(Map<String, Integer> headers, String[] cells) { Map<String, String> result = new HashMap<>(); for (var header : headers.entrySet()) result.put(header.getKey(), header.getValue() < cells.length ? cells[header.getValue()].trim() : null); return result; }
    private String cellText(Cell cell, FormulaEvaluator evaluator) { if (cell == null) return null; try { return new DataFormatter().formatCellValue(cell, evaluator).trim(); } catch (RuntimeException e) { return null; } }
    private String dateText(Cell cell, FormulaEvaluator evaluator, Integer businessYear) { LocalDate date = dateCell(cell, evaluator, businessYear); return date == null ? cellText(cell, evaluator) : date.toString(); }
    private LocalDate dateCell(Cell cell, FormulaEvaluator evaluator, Integer businessYear) {
        if (cell == null) return null;
        try {
            if (cell.getCellType() == CellType.NUMERIC) {
                double value = cell.getNumericCellValue();
                if (DateUtil.isCellDateFormatted(cell) || (value >= 20_000 && value <= 70_000)) {
                    return DateUtil.getLocalDateTime(value).toLocalDate();
                }
            }
            return parseDateValue(cellText(cell, evaluator), businessYear);
        } catch (RuntimeException e) { return null; }
    }
    private BigDecimal decimalCell(Row row, int column, FormulaEvaluator evaluator) { return row == null ? null : decimal(cellText(row.getCell(column), evaluator)); }
    private BigDecimal rateFromHeader(Cell cell, FormulaEvaluator evaluator) { String text = cellText(cell, evaluator); Matcher matcher = Pattern.compile("(\\d+(?:\\.\\d+)?)%", Pattern.CASE_INSENSITIVE).matcher(text == null ? "" : text); return matcher.find() ? new BigDecimal(matcher.group(1)).movePointLeft(2) : null; }
    private LocalDate parseDate(String raw, Integer businessYear) {
        LocalDate date = parseDateValue(raw, businessYear);
        if (businessYear != null && date.getYear() != businessYear) {
            throw ApiException.badRequest("IMPORT_DATE_OUTSIDE_BUSINESS_YEAR", "日期 " + date + " 不属于所选导入业务年份 " + businessYear);
        }
        return date;
    }

    /** Converts a date without enforcing the selected year, so legacy rows can become row-level validation errors. */
    private LocalDate parseDateValue(String raw, Integer businessYear) {
        if (raw == null || raw.isBlank()) throw ApiException.badRequest("IMPORT_DATE_REQUIRED", "缺少日期");
        String text = raw.trim();
        for (DateTimeFormatter formatter : List.of(DateTimeFormatter.ISO_LOCAL_DATE, DateTimeFormatter.ofPattern("yyyy/M/d"), DateTimeFormatter.ofPattern("M/d/yy"))) {
            try {
                return LocalDate.parse(text, formatter);
            } catch (DateTimeParseException ignored) { }
        }
        Matcher fullChineseDate = Pattern.compile("(\\d{4})年(\\d{1,2})月(\\d{1,2})日?").matcher(text);
        if (fullChineseDate.matches()) {
            return LocalDate.of(Integer.parseInt(fullChineseDate.group(1)), Integer.parseInt(fullChineseDate.group(2)), Integer.parseInt(fullChineseDate.group(3)));
        }
        Matcher monthDay = Pattern.compile("(\\d{1,2})月(\\d{1,2})日?").matcher(text);
        if (monthDay.matches()) {
            int year = businessYear == null ? currentBusinessYear() : businessYear;
            return LocalDate.of(year, Integer.parseInt(monthDay.group(1)), Integer.parseInt(monthDay.group(2)));
        }
        throw ApiException.badRequest("IMPORT_DATE_INVALID", "日期格式不正确：" + raw);
    }

    private int normalizeBusinessYear(Integer businessYear) {
        int year = businessYear == null ? currentBusinessYear() : businessYear;
        if (year < 1900 || year > 9999) throw ApiException.badRequest("IMPORT_BUSINESS_YEAR_INVALID", "请选择有效的导入业务年份");
        return year;
    }

    private int currentBusinessYear() {
        return java.time.Year.now(ZoneId.of(properties.businessZone())).getValue();
    }
    private BigDecimal decimal(String raw) {
        if (raw == null || raw.isBlank() || raw.equalsIgnoreCase("自动计算") || raw.equalsIgnoreCase("手动填写")
                || raw.contains("百分比可编辑") || raw.contains("手动填写") || raw.contains("自动计算")) return null;
        String normalized = raw.replace(",", "").replace("USDT", "").replace("USDC", "").trim();
        try { return new BigDecimal(normalized); }
        catch (NumberFormatException e) { throw ApiException.badRequest("IMPORT_CELL_INVALID_AMOUNT", "金额格式不正确：" + raw); }
    }
    private BigDecimal rate(String raw) {
        if (raw == null || raw.isBlank()) return null;
        boolean percentage = raw.contains("%");
        BigDecimal value = decimal(percentage ? raw.replace("%", "") : raw);
        if (value == null) return null;
        return percentage || value.compareTo(BigDecimal.ONE) > 0 ? value.movePointLeft(2) : value;
    }
    private String fraudSource(String raw) { if (raw == null || raw.isBlank()) return null; String v = raw.trim().toUpperCase(Locale.ROOT); return v.contains("TRANSFER") || v.contains("转账") ? "TRANSFER" : (v.contains("BALANCE") || v.contains("结余") || v.contains("余额") ? "BALANCE" : raw); }
    private String required(Map<String, String> values, String key, String error) { String value = values.get(key); if (value == null || value.isBlank()) throw ApiException.badRequest("IMPORT_FIELD_REQUIRED", error); return value; }
    private String first(String value, String fallback) { return value == null || value.isBlank() ? fallback : value.trim(); }
    private String trimToNull(String value) { return value == null || value.isBlank() ? null : value.trim(); }
    private String normalizeStrategy(String source) { String value = source == null || source.isBlank() ? "SKIP_EXISTING" : source.trim().toUpperCase(Locale.ROOT); if (!STRATEGIES.contains(value)) throw ApiException.badRequest("INVALID_IMPORT_STRATEGY", "导入冲突策略不合法"); return value; }
    private ParsedRow error(String sheet, int row, String operator, String code, String message, String raw) { return new ParsedRow(sheet, row, operator, null, code, message, raw); }
    private String serialize(Object value) { try { return objectMapper.writeValueAsString(value); } catch (JsonProcessingException e) { return "{}"; } }
    private BalanceDtos.DailyBalanceUpsertRequest deserialize(String value) { try { return objectMapper.readValue(value, BalanceDtos.DailyBalanceUpsertRequest.class); } catch (JsonProcessingException e) { throw ApiException.badRequest("IMPORT_DATA_CORRUPTED", "导入预览数据已损坏"); } }
    private String sha256(byte[] source) { try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(source)); } catch (Exception e) { throw new IllegalStateException(e); } }
    private ImportJob requireJob(Long id) {
        ImportJob job = jobRepository.findById(id).orElseThrow(() -> ApiException.notFound("导入批次"));
        if (operatorAccessService.hasAllOperators()) return job;
        if (!Objects.equals(job.getCreatedBy(), currentUser.require().id())
                || !isWithinCurrentScope(job, operatorAccessService.accessibleOperatorIds())) {
            throw ApiException.forbidden("只能访问自己创建的导入批次");
        }
        return job;
    }

    private List<ImportDtos.ImportRowResponse> rowsForJob(Long jobId) {
        return rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(jobId).stream().map(this::rowResponse).toList();
    }

    /**
     * A historical batch can contain raw source data.  Owners therefore retain access only while every row can be
     * traced to an account in their current operator scope.  Unmapped error rows are denied conservatively.
     */
    private boolean isWithinCurrentScope(ImportJob job, Set<Long> accessibleOperatorIds) {
        List<ImportJobRow> rows = rowRepository.findByImportJobIdOrderBySourceSheetAscSourceRowAsc(job.getId());
        if (rows.isEmpty()) return true;
        Set<Long> accountIds = new LinkedHashSet<>();
        for (ImportJobRow row : rows) {
            if (row.getOperatorAccountId() == null) return false;
            accountIds.add(row.getOperatorAccountId());
        }
        Map<Long, OperatorAccount> accounts = new HashMap<>();
        for (OperatorAccount account : accountRepository.findAllById(accountIds)) accounts.put(account.getId(), account);
        return accountIds.size() == accounts.size() && accounts.values().stream()
                .allMatch(account -> accessibleOperatorIds.contains(account.getOperatorId()));
    }
    private ImportDtos.ImportJobResponse jobResponse(ImportJob job) { return new ImportDtos.ImportJobResponse(job.getId(), job.getSourceType(), job.getOriginalFilename(), job.getFileSha256(), job.getCreatedBy(), job.getStatus(), job.getConflictStrategy(), job.getTotalRows(), job.getValidRows(), job.getWarningRows(), job.getErrorRows(), job.getCreatedAt(), job.getCommittedAt()); }
    private ImportDtos.ImportRowResponse rowResponse(ImportJobRow row) { return new ImportDtos.ImportRowResponse(row.getId(), row.getSourceSheet(), row.getSourceRow(), row.getOperatorName(), row.getOperatorAccountId(), row.getBusinessDate(), row.getSeverity(), row.getErrorCode(), row.getErrorMessage(), row.getAction(), row.getTargetDailyBalanceId(), row.getNormalizedJson() == null ? null : deserialize(row.getNormalizedJson())); }
    private record ParsedRow(String sheet, int row, String operatorName, BalanceDtos.DailyBalanceUpsertRequest command, String errorCode, String errorMessage, String raw) { }
    private record ParsedWorkbook(String sourceType, List<ParsedRow> rows) { }
    public record XlsxDownload(String filename, byte[] content) { }
}
