package com.rajads.erp.balance;

import com.rajads.erp.audit.AuditService;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.operator.OperatorAccount;
import com.rajads.erp.operator.OperatorService;
import com.rajads.erp.shared.ApiException;
import com.rajads.erp.shared.DecimalUtils;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.*;

@Service
@RequiredArgsConstructor
public class BalanceService {
    private final DailyBalanceRepository repository;
    private final AccountingPeriodLockRepository lockRepository;
    private final OperatorService operatorService;
    private final CurrentUser currentUser;
    private final AuditService auditService;

    @Transactional(readOnly = true)
    public BalanceDtos.DailyBalanceListResponse list(Long accountId, YearMonth month) {
        OperatorAccount account = operatorService.requireAccount(accountId);
        List<BalanceDtos.DailyBalanceResponse> records = repository
                .findByOperatorAccountIdAndBusinessDateBetweenOrderByBusinessDateAsc(accountId, month.atDay(1), month.atEndOfMonth())
                .stream().map(this::response).toList();
        return new BalanceDtos.DailyBalanceListResponse(account.getId(), month.toString(), records);
    }

    @Transactional(readOnly = true)
    public BalanceDtos.CalculationPreviewResponse calculationPreview(BalanceDtos.DailyBalanceUpsertRequest request) {
        OperatorAccount account = operatorService.requireAccount(request.operatorAccountId());
        DailyBalance prototype = new DailyBalance();
        prototype.setOperatorAccountId(account.getId());
        prototype.setBusinessDate(request.businessDate());
        applyRequest(prototype, request, account, true, false);
        return calculationResponse(prototype);
    }

    @Transactional(readOnly = true)
    public BalanceDtos.ImpactPreviewResponse impactPreview(BalanceDtos.DailyBalanceUpsertRequest request) {
        OperatorAccount account = operatorService.requireAccount(request.operatorAccountId());
        DailyBalance proposed = repository.findByOperatorAccountIdAndBusinessDate(account.getId(), request.businessDate())
                .map(this::copy).orElseGet(DailyBalance::new);
        proposed.setOperatorAccountId(account.getId());
        proposed.setBusinessDate(request.businessDate());
        applyRequest(proposed, request, account, proposed.getId() == null, false);
        List<BalanceDtos.ImpactedRecord> impacted = new ArrayList<>();
        List<String> blocking = new ArrayList<>();
        BigDecimal carriedClosing = proposed.getClosingBalance();
        for (DailyBalance next : repository.findByOperatorAccountIdAndBusinessDateAfterOrderByBusinessDateAsc(account.getId(), request.businessDate())) {
            if (!"AUTO".equals(next.getOpeningMode())) break;
            if (!"DRAFT".equals(next.getStatus())) {
                blocking.add(next.getBusinessDate() + " 已确认，修改前序记录后需要先重开");
                break;
            }
            if (isLocked(next.getOperatorAccountId(), next.getBusinessDate())) {
                blocking.add(next.getBusinessDate() + " 所在月份已锁定");
                break;
            }
            DailyBalance simulated = copy(next);
            BigDecimal previousOpening = simulated.getOpeningBalance();
            BigDecimal previousClosing = simulated.getClosingBalance();
            simulated.setSuggestedOpeningBalance(carriedClosing);
            simulated.setOpeningBalance(carriedClosing);
            recalculateDerived(simulated);
            impacted.add(new BalanceDtos.ImpactedRecord(simulated.getId(), simulated.getBusinessDate(), previousOpening,
                    simulated.getOpeningBalance(), previousClosing, simulated.getClosingBalance()));
            carriedClosing = simulated.getClosingBalance();
        }
        return new BalanceDtos.ImpactPreviewResponse(calculationResponse(proposed), impacted, blocking);
    }

    @Transactional
    public BalanceDtos.DailyBalanceResponse create(BalanceDtos.DailyBalanceUpsertRequest request) {
        if (repository.findByOperatorAccountIdAndBusinessDate(request.operatorAccountId(), request.businessDate()).isPresent()) {
            throw ApiException.conflict("DAILY_BALANCE_EXISTS", "该投放线该日期已有日结记录");
        }
        OperatorAccount account = operatorService.requireAccount(request.operatorAccountId());
        if (isLocked(account.getId(), request.businessDate())) throw locked();
        DailyBalance balance = new DailyBalance();
        balance.setOperatorAccountId(account.getId());
        balance.setBusinessDate(request.businessDate());
        applyRequest(balance, request, account, true, false);
        balance.setCreatedBy(currentUser.require().id());
        balance.setUpdatedBy(currentUser.require().id());
        balance = repository.save(balance);
        List<BalanceDtos.ImpactedRecord> impacted = cascadeRecalculate(balance);
        BalanceDtos.DailyBalanceResponse result = response(balance);
        auditService.record("DAILY_BALANCE_CREATED", "DAILY_BALANCE", balance.getId().toString(), account.getOperatorId(), null,
                Map.of("record", result, "impactedRecords", impacted));
        return result;
    }

    @Transactional
    public BalanceDtos.DailyBalanceResponse update(Long id, BalanceDtos.DailyBalanceUpsertRequest request) {
        DailyBalance balance = requireBalance(id);
        OperatorAccount account = operatorService.requireAccount(balance.getOperatorAccountId());
        ensureModifiable(balance);
        if (request.operatorAccountId() != null && !Objects.equals(request.operatorAccountId(), balance.getOperatorAccountId())) {
            throw ApiException.badRequest("ACCOUNT_IMMUTABLE", "已存在日结记录不能更换投放线");
        }
        if (request.businessDate() != null && !Objects.equals(request.businessDate(), balance.getBusinessDate())) {
            throw ApiException.badRequest("DATE_IMMUTABLE", "已存在日结记录不能更换业务日期");
        }
        if (request.rowVersion() == null || !Objects.equals(request.rowVersion(), balance.getRowVersion())) {
            throw ApiException.conflict("BALANCE_VERSION_CONFLICT", "日结记录已被其他人修改");
        }
        BalanceDtos.DailyBalanceResponse before = response(balance);
        applyRequest(balance, request, account, false, false);
        balance.setUpdatedBy(currentUser.require().id());
        balance = repository.save(balance);
        List<BalanceDtos.ImpactedRecord> impacted = cascadeRecalculate(balance);
        BalanceDtos.DailyBalanceResponse result = response(balance);
        auditService.record("DAILY_BALANCE_UPDATED", "DAILY_BALANCE", id.toString(), account.getOperatorId(), before,
                Map.of("record", result, "impactedRecords", impacted));
        return result;
    }

    @Transactional
    public List<BalanceDtos.DailyBalanceResponse> batch(BalanceDtos.BatchRequest request) {
        if (request.records() == null || request.records().isEmpty()) {
            throw ApiException.badRequest("BATCH_EMPTY", "至少需要一条记录");
        }
        Set<String> keys = new HashSet<>();
        for (BalanceDtos.DailyBalanceUpsertRequest row : request.records()) {
            String key = row.operatorAccountId() + "|" + row.businessDate();
            if (!keys.add(key)) throw ApiException.badRequest("BATCH_DUPLICATE", "批量数据中存在重复投放线和日期");
        }
        List<BalanceDtos.DailyBalanceResponse> results = new ArrayList<>();
        for (BalanceDtos.DailyBalanceUpsertRequest row : request.records()) {
            Optional<DailyBalance> existing = repository.findByOperatorAccountIdAndBusinessDate(row.operatorAccountId(), row.businessDate());
            results.add(existing.map(balance -> update(balance.getId(), row)).orElseGet(() -> create(row)));
        }
        return results;
    }

    @Transactional
    public BalanceDtos.DailyBalanceResponse confirm(Long id, BalanceDtos.ConfirmRequest request) {
        DailyBalance balance = requireBalance(id);
        ensureNotLocked(balance);
        verifyVersion(balance.getRowVersion(), request == null ? null : request.rowVersion());
        if (!"DRAFT".equals(balance.getStatus())) throw ApiException.conflict("BALANCE_NOT_DRAFT", "只有草稿可确认");
        balance.setStatus("CONFIRMED");
        balance.setConfirmedBy(currentUser.require().id());
        balance.setConfirmedAt(Instant.now());
        balance = repository.save(balance);
        BalanceDtos.DailyBalanceResponse result = response(balance);
        auditService.record("DAILY_BALANCE_CONFIRMED", "DAILY_BALANCE", id.toString(), operatorService.requireAccount(balance.getOperatorAccountId()).getOperatorId(), null, result);
        return result;
    }

    @Transactional
    public BalanceDtos.DailyBalanceResponse reopen(Long id, BalanceDtos.ReopenRequest request) {
        DailyBalance balance = requireBalance(id);
        ensureNotLocked(balance);
        verifyVersion(balance.getRowVersion(), request == null ? null : request.rowVersion());
        if (request == null || request.reason() == null || request.reason().isBlank()) {
            throw ApiException.badRequest("REOPEN_REASON_REQUIRED", "重开日结必须填写原因");
        }
        BalanceDtos.DailyBalanceResponse before = response(balance);
        balance.setStatus("DRAFT");
        balance.setConfirmedBy(null);
        balance.setConfirmedAt(null);
        balance = repository.save(balance);
        BalanceDtos.DailyBalanceResponse result = response(balance);
        auditService.record("DAILY_BALANCE_REOPENED", "DAILY_BALANCE", id.toString(), operatorService.requireAccount(balance.getOperatorAccountId()).getOperatorId(), before,
                Map.of("record", result, "reason", request.reason()));
        return result;
    }

    /** Used by the import transaction. Existing records are handled by its conflict strategy. */
    @Transactional
    public BalanceDtos.DailyBalanceResponse createImported(BalanceDtos.DailyBalanceUpsertRequest request) {
        return create(requestWithSource(request, "IMPORT"));
    }

    @Transactional
    public BalanceDtos.DailyBalanceResponse updateImported(Long id, BalanceDtos.DailyBalanceUpsertRequest request,
                                                            Long expectedRowVersion) {
        if (expectedRowVersion == null) {
            throw ApiException.conflict("IMPORT_PREVIEW_STALE", "导入预检缺少目标草稿版本，请重新预检后提交");
        }
        return update(id, requestWithVersionAndSource(request, expectedRowVersion, "IMPORT"));
    }

    @Transactional(readOnly = true)
    public DailyBalance requireBalance(Long id) {
        DailyBalance balance = repository.findById(id).orElseThrow(() -> ApiException.notFound("日结记录"));
        operatorService.requireAccount(balance.getOperatorAccountId());
        return balance;
    }

    public BalanceDtos.DailyBalanceResponse response(DailyBalance balance) {
        return new BalanceDtos.DailyBalanceResponse(balance.getId(), balance.getOperatorAccountId(), balance.getBusinessDate(),
                balance.getOpeningBalance(), balance.getSuggestedOpeningBalance(), balance.getOpeningMode(), balance.getOpeningOverrideReason(),
                balance.getTransferAmount(), balance.getFraudLossAmount(), balance.getFraudDeductionSource(), balance.getEffectiveTransferAmount(),
                balance.getSpendAmount(), balance.getExchangeLossRate(), balance.getExchangeLossBasis(), balance.getExchangeLossAutoAmount(),
                balance.getExchangeLossAmount(), balance.getExchangeLossMode(), balance.getExchangeLossOverrideReason(),
                balance.getServiceFeeRate(), balance.getServiceFeeBasis(), balance.getServiceFeeAutoAmount(), balance.getServiceFeeAmount(),
                balance.getServiceFeeMode(), balance.getServiceFeeOverrideReason(), balance.getRefluxAmount(), balance.getRefundAmount(),
                balance.getOtherDeductionAmount(), balance.getOtherReason(), balance.getClosingBalance(), balance.getCalculationScale(),
                balance.getStatus(), balance.getSourceType(), balance.getRemark(), isLocked(balance.getOperatorAccountId(), balance.getBusinessDate()),
                balance.getRowVersion(), balance.getCreatedAt(), balance.getUpdatedAt());
    }

    private void applyRequest(DailyBalance balance, BalanceDtos.DailyBalanceUpsertRequest request, OperatorAccount account,
                              boolean isNew, boolean systemRecalculation) {
        if (request.businessDate() == null) throw ApiException.badRequest("BUSINESS_DATE_REQUIRED", "业务日期不能为空");
        if (isNew) initializeFromAccount(balance, account);
        DailyBalance previous = repository.findFirstByOperatorAccountIdAndBusinessDateBeforeOrderByBusinessDateDesc(account.getId(), request.businessDate())
                .orElse(null);
        BigDecimal suggested = previous == null ? null : previous.getClosingBalance();
        balance.setSuggestedOpeningBalance(suggested);
        String requestedOpeningMode = request.openingMode() == null ? null : request.openingMode().trim().toUpperCase(Locale.ROOT);
        String openingMode = requestedOpeningMode == null ? balance.getOpeningMode() : requestedOpeningMode;
        if (isNew && requestedOpeningMode == null) {
            openingMode = suggested == null ? "MANUAL" : "AUTO";
        }
        if (!Set.of("AUTO", "MANUAL").contains(openingMode)) throw ApiException.badRequest("INVALID_OPENING_MODE", "期初模式必须为 AUTO 或 MANUAL");
        balance.setOpeningMode(openingMode);
        if ("AUTO".equals(openingMode)) {
            if (suggested == null) throw ApiException.badRequest("OPENING_BALANCE_REQUIRED", "没有历史记录时必须填写人工期初结余");
            balance.setOpeningBalance(suggested);
            balance.setOpeningOverrideReason(null);
        } else {
            BigDecimal opening = request.openingBalance() == null ? balance.getOpeningBalance() : request.openingBalance();
            if (opening == null) throw ApiException.badRequest("OPENING_BALANCE_REQUIRED", "人工期初结余不能为空");
            String reason = request.openingOverrideReason() == null ? balance.getOpeningOverrideReason() : trimToNull(request.openingOverrideReason());
            balance.setOpeningBalance(DecimalUtils.amount(opening));
            balance.setOpeningOverrideReason(reason);
        }

        balance.setTransferAmount(amountOrExisting(request.transferAmount(), balance.getTransferAmount(), "转U"));
        balance.setFraudLossAmount(amountOrExisting(request.fraudLossAmount(), balance.getFraudLossAmount(), "欺诈损失"));
        balance.setSpendAmount(amountOrExisting(request.spendAmount(), balance.getSpendAmount(), "消耗"));
        balance.setRefluxAmount(amountOrExisting(request.refluxAmount(), balance.getRefluxAmount(), "回流"));
        balance.setRefundAmount(amountOrExisting(request.refundAmount(), balance.getRefundAmount(), "退款"));
        balance.setOtherDeductionAmount(amountOrExisting(request.otherDeductionAmount(), balance.getOtherDeductionAmount(), "其他"));
        balance.setOtherReason(request.otherReason() == null ? balance.getOtherReason() : trimToNull(request.otherReason()));
        if (balance.getOtherDeductionAmount().signum() > 0 && (balance.getOtherReason() == null || balance.getOtherReason().isBlank())) {
            throw ApiException.badRequest("OTHER_REASON_REQUIRED", "其他扣减金额不为 0 时必须填写原因");
        }
        balance.setFraudDeductionSource(normalizeFraudSource(request.fraudDeductionSource(), balance.getFraudDeductionSource(), balance.getFraudLossAmount()));

        balance.setExchangeLossRate(rateOrExisting(request.exchangeLossRate(), balance.getExchangeLossRate(), "汇损费率"));
        balance.setExchangeLossBasis(basisOrExisting(request.exchangeLossBasis(), balance.getExchangeLossBasis()));
        balance.setExchangeLossMode(modeOrExisting(request.exchangeLossMode(), balance.getExchangeLossMode()));
        balance.setExchangeLossOverrideReason(request.exchangeLossOverrideReason() == null ? balance.getExchangeLossOverrideReason() : trimToNull(request.exchangeLossOverrideReason()));
        if (request.exchangeLossAmount() != null || "MANUAL".equals(balance.getExchangeLossMode()) || "MANUAL".equals(balance.getExchangeLossBasis())) {
            if (request.exchangeLossAmount() != null) balance.setExchangeLossAmount(amountOrExisting(request.exchangeLossAmount(), BigDecimal.ZERO, "汇损金额"));
        }
        normalizeManualFee(balance.getExchangeLossBasis(), balance.getExchangeLossMode(), balance.getExchangeLossAmount(), "汇损", systemRecalculation);

        balance.setServiceFeeRate(rateOrExisting(request.serviceFeeRate(), balance.getServiceFeeRate(), "服务费率"));
        balance.setServiceFeeBasis(basisOrExisting(request.serviceFeeBasis(), balance.getServiceFeeBasis()));
        balance.setServiceFeeMode(modeOrExisting(request.serviceFeeMode(), balance.getServiceFeeMode()));
        balance.setServiceFeeOverrideReason(request.serviceFeeOverrideReason() == null ? balance.getServiceFeeOverrideReason() : trimToNull(request.serviceFeeOverrideReason()));
        if (request.serviceFeeAmount() != null || "MANUAL".equals(balance.getServiceFeeMode()) || "MANUAL".equals(balance.getServiceFeeBasis())) {
            if (request.serviceFeeAmount() != null) balance.setServiceFeeAmount(amountOrExisting(request.serviceFeeAmount(), BigDecimal.ZERO, "服务费金额"));
        }
        normalizeManualFee(balance.getServiceFeeBasis(), balance.getServiceFeeMode(), balance.getServiceFeeAmount(), "服务费", systemRecalculation);

        Integer scale = request.calculationScale() == null ? balance.getCalculationScale() : request.calculationScale();
        if (scale == null) scale = account.getCalculationScale();
        if (scale < 0 || scale > 8) throw ApiException.badRequest("INVALID_CALCULATION_SCALE", "计算精度必须在 0 到 8 之间");
        balance.setCalculationScale(scale);
        if (request.sourceType() != null) balance.setSourceType(normalizeSourceType(request.sourceType()));
        if (request.remark() != null) balance.setRemark(trimToNull(request.remark()));
        recalculateDerived(balance);
    }

    private void initializeFromAccount(DailyBalance balance, OperatorAccount account) {
        balance.setOpeningMode("AUTO");
        balance.setTransferAmount(BigDecimal.ZERO); balance.setFraudLossAmount(BigDecimal.ZERO); balance.setSpendAmount(BigDecimal.ZERO);
        balance.setRefluxAmount(BigDecimal.ZERO); balance.setRefundAmount(BigDecimal.ZERO); balance.setOtherDeductionAmount(BigDecimal.ZERO);
        balance.setExchangeLossRate(account.getDefaultExchangeLossRate());
        balance.setExchangeLossBasis(account.getDefaultExchangeLossBasis());
        balance.setExchangeLossMode("AUTO");
        balance.setExchangeLossAmount(BigDecimal.ZERO);
        balance.setServiceFeeRate(account.getDefaultServiceFeeRate());
        balance.setServiceFeeBasis(account.getDefaultServiceFeeBasis());
        balance.setServiceFeeMode("AUTO");
        balance.setServiceFeeAmount(BigDecimal.ZERO);
        balance.setCalculationScale(account.getCalculationScale());
        balance.setStatus("DRAFT");
        balance.setSourceType("MANUAL");
    }

    private void recalculateDerived(DailyBalance balance) {
        FraudDeductionSource fraudSource = balance.getFraudDeductionSource() == null ? null : FraudDeductionSource.valueOf(balance.getFraudDeductionSource());
        BalanceCalculation.Result result = BalanceCalculation.calculate(balance.getOpeningBalance(), balance.getTransferAmount(),
                balance.getFraudLossAmount(), fraudSource, balance.getSpendAmount(),
                new BalanceCalculation.Fee(balance.getExchangeLossRate(), CalculationBasis.valueOf(balance.getExchangeLossBasis()),
                        balance.getExchangeLossMode(), balance.getExchangeLossAmount()),
                new BalanceCalculation.Fee(balance.getServiceFeeRate(), CalculationBasis.valueOf(balance.getServiceFeeBasis()),
                        balance.getServiceFeeMode(), balance.getServiceFeeAmount()),
                balance.getRefluxAmount(), balance.getRefundAmount(), balance.getOtherDeductionAmount(), balance.getCalculationScale());
        balance.setEffectiveTransferAmount(result.effectiveTransferAmount());
        balance.setExchangeLossAutoAmount(result.exchangeLossAutoAmount());
        balance.setExchangeLossAmount(result.exchangeLossAmount());
        balance.setServiceFeeAutoAmount(result.serviceFeeAutoAmount());
        balance.setServiceFeeAmount(result.serviceFeeAmount());
        balance.setClosingBalance(result.closingBalance());
    }

    private List<BalanceDtos.ImpactedRecord> cascadeRecalculate(DailyBalance changed) {
        List<BalanceDtos.ImpactedRecord> impacts = new ArrayList<>();
        BigDecimal carrying = changed.getClosingBalance();
        for (DailyBalance next : repository.findByOperatorAccountIdAndBusinessDateAfterOrderByBusinessDateAsc(changed.getOperatorAccountId(), changed.getBusinessDate())) {
            if (!"AUTO".equals(next.getOpeningMode())) break;
            if (!"DRAFT".equals(next.getStatus())) {
                throw ApiException.conflict("CASCADE_BLOCKED_BY_CONFIRMED", next.getBusinessDate() + " 已确认，不能静默重算");
            }
            if (isLocked(next.getOperatorAccountId(), next.getBusinessDate())) throw locked();
            BigDecimal oldOpening = next.getOpeningBalance();
            BigDecimal oldClosing = next.getClosingBalance();
            next.setSuggestedOpeningBalance(carrying);
            next.setOpeningBalance(carrying);
            recalculateDerived(next);
            next.setUpdatedBy(currentUser.require().id());
            repository.save(next);
            impacts.add(new BalanceDtos.ImpactedRecord(next.getId(), next.getBusinessDate(), oldOpening, next.getOpeningBalance(), oldClosing, next.getClosingBalance()));
            carrying = next.getClosingBalance();
        }
        return impacts;
    }

    private boolean isLocked(Long accountId, LocalDate date) {
        return lockRepository.findByOperatorAccountIdAndPeriodMonth(accountId, date.withDayOfMonth(1))
                .map(lock -> "LOCKED".equals(lock.getStatus())).orElse(false);
    }
    private void ensureModifiable(DailyBalance balance) {
        ensureNotLocked(balance);
        if (!"DRAFT".equals(balance.getStatus())) throw ApiException.conflict("BALANCE_NOT_DRAFT", "已确认日结必须先重开");
    }
    private void ensureNotLocked(DailyBalance balance) { if (isLocked(balance.getOperatorAccountId(), balance.getBusinessDate())) throw locked(); }
    private ApiException locked() { return ApiException.conflict("PERIOD_LOCKED", "该业务月份已锁定"); }
    private void verifyVersion(Long actual, Long requested) {
        if (requested == null || !Objects.equals(actual, requested)) throw ApiException.conflict("BALANCE_VERSION_CONFLICT", "日结记录已被其他人修改");
    }
    private BigDecimal amountOrExisting(BigDecimal requested, BigDecimal existing, String label) {
        BigDecimal value = requested == null ? DecimalUtils.zeroIfNull(existing) : requested;
        DecimalUtils.requireNonNegative(label, value);
        return DecimalUtils.amount(value);
    }
    private BigDecimal rateOrExisting(BigDecimal requested, BigDecimal existing, String label) {
        BigDecimal rate = requested == null ? DecimalUtils.zeroIfNull(existing) : requested;
        DecimalUtils.requireNonNegative(label, rate);
        if (rate.compareTo(BigDecimal.ONE) > 0) throw ApiException.badRequest("INVALID_RATE", label + "不得大于 1；2% 请传 0.02");
        return rate;
    }
    private String basisOrExisting(String requested, String existing) {
        String candidate = requested == null ? existing : requested;
        try { return CalculationBasis.valueOf(candidate.trim().toUpperCase(Locale.ROOT)).name(); }
        catch (Exception e) { throw ApiException.badRequest("INVALID_CALCULATION_BASIS", "不支持的计算基数"); }
    }
    private String modeOrExisting(String requested, String existing) {
        String candidate = requested == null ? existing : requested;
        candidate = candidate == null ? "AUTO" : candidate.trim().toUpperCase(Locale.ROOT);
        if (!Set.of("AUTO", "MANUAL").contains(candidate)) throw ApiException.badRequest("INVALID_CALCULATION_MODE", "计算模式必须为 AUTO 或 MANUAL");
        return candidate;
    }
    private String normalizeFraudSource(String requested, String existing, BigDecimal fraudAmount) {
        if (fraudAmount.signum() == 0) return null;
        String candidate = requested == null ? existing : requested;
        if (candidate == null || candidate.isBlank()) throw ApiException.badRequest("FRAUD_SOURCE_REQUIRED", "欺诈损失不为 0 时必须选择承担方式");
        try { return FraudDeductionSource.valueOf(candidate.trim().toUpperCase(Locale.ROOT)).name(); }
        catch (Exception e) { throw ApiException.badRequest("INVALID_FRAUD_SOURCE", "欺诈承担方式必须为 TRANSFER 或 BALANCE"); }
    }
    private String normalizeSourceType(String source) {
        String normalized = source.trim().toUpperCase(Locale.ROOT);
        if (!Set.of("MANUAL", "PASTE", "IMPORT").contains(normalized)) throw ApiException.badRequest("INVALID_SOURCE_TYPE", "来源类型不合法");
        return normalized;
    }
    private void normalizeManualFee(String basis, String mode, BigDecimal amount, String label, boolean systemRecalculation) {
        boolean manual = "MANUAL".equals(basis) || "MANUAL".equals(mode);
        if (!manual) return;
        DecimalUtils.requireNonNegative(label + "金额", amount);
        if (!systemRecalculation && !currentUser.require().permissions().contains("BALANCE_OVERRIDE")) {
            throw ApiException.forbidden("没有手工覆盖自动金额的权限");
        }
    }
    private String trimToNull(String value) { return value == null || value.isBlank() ? null : value.trim(); }

    private DailyBalance copy(DailyBalance source) {
        DailyBalance copy = new DailyBalance();
        copy.setId(source.getId()); copy.setOperatorAccountId(source.getOperatorAccountId()); copy.setBusinessDate(source.getBusinessDate());
        copy.setOpeningBalance(source.getOpeningBalance()); copy.setSuggestedOpeningBalance(source.getSuggestedOpeningBalance()); copy.setOpeningMode(source.getOpeningMode()); copy.setOpeningOverrideReason(source.getOpeningOverrideReason());
        copy.setTransferAmount(source.getTransferAmount()); copy.setFraudLossAmount(source.getFraudLossAmount()); copy.setFraudDeductionSource(source.getFraudDeductionSource()); copy.setEffectiveTransferAmount(source.getEffectiveTransferAmount()); copy.setSpendAmount(source.getSpendAmount());
        copy.setExchangeLossRate(source.getExchangeLossRate()); copy.setExchangeLossBasis(source.getExchangeLossBasis()); copy.setExchangeLossAutoAmount(source.getExchangeLossAutoAmount()); copy.setExchangeLossAmount(source.getExchangeLossAmount()); copy.setExchangeLossMode(source.getExchangeLossMode()); copy.setExchangeLossOverrideReason(source.getExchangeLossOverrideReason());
        copy.setServiceFeeRate(source.getServiceFeeRate()); copy.setServiceFeeBasis(source.getServiceFeeBasis()); copy.setServiceFeeAutoAmount(source.getServiceFeeAutoAmount()); copy.setServiceFeeAmount(source.getServiceFeeAmount()); copy.setServiceFeeMode(source.getServiceFeeMode()); copy.setServiceFeeOverrideReason(source.getServiceFeeOverrideReason());
        copy.setRefluxAmount(source.getRefluxAmount()); copy.setRefundAmount(source.getRefundAmount()); copy.setOtherDeductionAmount(source.getOtherDeductionAmount()); copy.setOtherReason(source.getOtherReason()); copy.setClosingBalance(source.getClosingBalance());
        copy.setCalculationScale(source.getCalculationScale()); copy.setStatus(source.getStatus()); copy.setSourceType(source.getSourceType()); copy.setRemark(source.getRemark()); copy.setRowVersion(source.getRowVersion());
        return copy;
    }
    private BalanceDtos.CalculationPreviewResponse calculationResponse(DailyBalance balance) {
        BigDecimal fraudTransfer = "TRANSFER".equals(balance.getFraudDeductionSource()) ? balance.getFraudLossAmount() : BigDecimal.ZERO;
        BigDecimal fraudBalance = "BALANCE".equals(balance.getFraudDeductionSource()) ? balance.getFraudLossAmount() : BigDecimal.ZERO;
        return new BalanceDtos.CalculationPreviewResponse(balance.getSuggestedOpeningBalance(), balance.getOpeningBalance(), balance.getEffectiveTransferAmount(),
                balance.getExchangeLossAutoAmount(), balance.getExchangeLossAmount(), balance.getServiceFeeAutoAmount(), balance.getServiceFeeAmount(),
                fraudTransfer, fraudBalance, balance.getClosingBalance());
    }
    private BalanceDtos.DailyBalanceUpsertRequest requestWithSource(BalanceDtos.DailyBalanceUpsertRequest r, String source) {
        return new BalanceDtos.DailyBalanceUpsertRequest(r.operatorAccountId(), r.businessDate(), r.openingBalance(), r.openingMode(), r.openingOverrideReason(), r.transferAmount(), r.fraudLossAmount(), r.fraudDeductionSource(), r.spendAmount(), r.exchangeLossRate(), r.exchangeLossBasis(), r.exchangeLossMode(), r.exchangeLossAmount(), r.exchangeLossOverrideReason(), r.serviceFeeRate(), r.serviceFeeBasis(), r.serviceFeeMode(), r.serviceFeeAmount(), r.serviceFeeOverrideReason(), r.refluxAmount(), r.refundAmount(), r.otherDeductionAmount(), r.otherReason(), r.calculationScale(), source, r.remark(), r.rowVersion());
    }
    private BalanceDtos.DailyBalanceUpsertRequest requestWithVersionAndSource(BalanceDtos.DailyBalanceUpsertRequest r, Long version, String source) {
        BalanceDtos.DailyBalanceUpsertRequest sourced = requestWithSource(r, source);
        return new BalanceDtos.DailyBalanceUpsertRequest(sourced.operatorAccountId(), sourced.businessDate(), sourced.openingBalance(), sourced.openingMode(), sourced.openingOverrideReason(), sourced.transferAmount(), sourced.fraudLossAmount(), sourced.fraudDeductionSource(), sourced.spendAmount(), sourced.exchangeLossRate(), sourced.exchangeLossBasis(), sourced.exchangeLossMode(), sourced.exchangeLossAmount(), sourced.exchangeLossOverrideReason(), sourced.serviceFeeRate(), sourced.serviceFeeBasis(), sourced.serviceFeeMode(), sourced.serviceFeeAmount(), sourced.serviceFeeOverrideReason(), sourced.refluxAmount(), sourced.refundAmount(), sourced.otherDeductionAmount(), sourced.otherReason(), sourced.calculationScale(), sourced.sourceType(), sourced.remark(), version);
    }
}
