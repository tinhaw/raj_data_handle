package com.rajads.erp.operator;

import com.rajads.erp.audit.AuditService;
import com.rajads.erp.balance.AccountingPeriodLockRepository;
import com.rajads.erp.balance.DailyBalanceRepository;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.identity.OperatorAccessService;
import com.rajads.erp.shared.ApiException;
import com.rajads.erp.shared.DecimalUtils;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.*;

@Service
@RequiredArgsConstructor
public class OperatorService {
    private static final Set<String> OPERATOR_TYPES = Set.of("COMPANY", "STUDIO", "INDIVIDUAL");
    private static final Set<String> BASES = Set.of("TRANSFER", "EFFECTIVE_TRANSFER", "SPEND", "MANUAL");
    private static final Set<String> ASSETS = Set.of("USDT", "USDC");
    /** Preserve the previous new-account defaults after moving them out of the UI. */
    private static final BigDecimal DEFAULT_LINE_RATE = new BigDecimal("0.02");
    private final OperatorRepository operatorRepository;
    private final OperatorAccountRepository accountRepository;
    private final DailyBalanceRepository balanceRepository;
    private final AccountingPeriodLockRepository lockRepository;
    private final OperatorAccessService accessService;
    private final CurrentUser currentUser;
    private final AuditService auditService;

    @Transactional(readOnly = true)
    public List<OperatorDtos.OperatorResponse> list(String search, boolean includeInactive) {
        List<Operator> operators;
        if (search == null || search.isBlank()) {
            operators = accessService.hasAllOperators() ? operatorRepository.findAll()
                    : operatorRepository.findByIdIn(accessService.accessibleOperatorIds());
        } else {
            operators = operatorRepository.findByNameContainingIgnoreCaseOrCodeContainingIgnoreCase(search.trim(), search.trim());
            if (!accessService.hasAllOperators()) {
                Set<Long> allowed = accessService.accessibleOperatorIds();
                operators = operators.stream().filter(operator -> allowed.contains(operator.getId())).toList();
            }
        }
        return operators.stream().filter(operator -> includeInactive || "ACTIVE".equals(operator.getStatus()))
                .sorted(Comparator.comparing(Operator::getName, String.CASE_INSENSITIVE_ORDER)).map(this::operatorResponse).toList();
    }

    @Transactional(readOnly = true)
    public OperatorDtos.OperatorDetailResponse get(Long id) {
        Operator operator = requireOperator(id);
        return new OperatorDtos.OperatorDetailResponse(operatorResponse(operator), accounts(id));
    }

    @Transactional
    public OperatorDtos.OperatorResponse create(OperatorDtos.OperatorRequest request) {
        String name = requiredName(request.name(), "投放公司名称");
        ensureCompanyNameAvailable(name, null);
        Operator operator = new Operator();
        // The new UI never asks for a code, but an explicit legacy API code
        // remains supported so existing import integrations do not break.
        operator.setCode(requestedOrGeneratedCompanyCode(request.code()));
        operator.setName(name);
        operator.setOperatorType(normalizeOperatorType(request.operatorType()));
        operator.setContactName(trimToNull(request.contactName()));
        operator.setContactValue(trimToNull(request.contactValue()));
        operator.setRemark(trimToNull(request.remark()));
        operator.setCreatedBy(currentUser.require().id());
        operator.setUpdatedBy(currentUser.require().id());
        operator = operatorRepository.save(operator);
        OperatorDtos.OperatorResponse result = operatorResponse(operator);
        auditService.record("OPERATOR_CREATED", "OPERATOR", operator.getId().toString(), operator.getId(), null, result);
        return result;
    }

    @Transactional
    public OperatorDtos.OperatorResponse patch(Long id, OperatorDtos.OperatorPatchRequest request) {
        Operator operator = requireOperator(id);
        verifyVersion(operator.getRowVersion(), request.rowVersion(), "OPERATOR_VERSION_CONFLICT", "投放公司已被其他人修改");
        OperatorDtos.OperatorResponse before = operatorResponse(operator);
        if (request.name() != null && !request.name().isBlank()) {
            String name = requiredName(request.name(), "投放公司名称");
            if (!sameName(operator.getName(), name)) ensureCompanyNameAvailable(name, id);
            operator.setName(name);
        }
        if (request.operatorType() != null) operator.setOperatorType(normalizeOperatorType(request.operatorType()));
        if (request.contactName() != null) operator.setContactName(trimToNull(request.contactName()));
        if (request.contactValue() != null) operator.setContactValue(trimToNull(request.contactValue()));
        if (request.remark() != null) operator.setRemark(trimToNull(request.remark()));
        operator.setUpdatedBy(currentUser.require().id());
        operator = operatorRepository.save(operator);
        OperatorDtos.OperatorResponse result = operatorResponse(operator);
        auditService.record("OPERATOR_UPDATED", "OPERATOR", id.toString(), id, before, result);
        return result;
    }

    @Transactional
    public OperatorDtos.OperatorResponse disable(Long id, OperatorDtos.DisableRequest request) {
        Operator operator = requireOperator(id);
        verifyVersion(operator.getRowVersion(), request.rowVersion(), "OPERATOR_VERSION_CONFLICT", "投放公司已被其他人修改");
        OperatorDtos.OperatorResponse before = operatorResponse(operator);
        operator.setStatus("INACTIVE");
        operator.setUpdatedBy(currentUser.require().id());
        operator = operatorRepository.save(operator);
        OperatorDtos.OperatorResponse result = operatorResponse(operator);
        auditService.record("OPERATOR_DISABLED", "OPERATOR", id.toString(), id, before, Map.of("result", result, "reason", request.reason()));
        return result;
    }

    /**
     * Deletes a company and its delivery lines. Historical ledgers are purged
     * only after the caller explicitly confirms that destructive action.
     */
    @Transactional
    public void delete(Long id, OperatorDtos.DeleteRequest request) {
        Operator operator = requireOperator(id);
        verifyVersion(operator.getRowVersion(), request.rowVersion(), "OPERATOR_VERSION_CONFLICT", "投放公司已被其他人修改");
        List<OperatorAccount> lines = accountRepository.findByOperatorIdOrderByAssetAscCodeAsc(id);
        List<Long> lineIds = lines.stream().map(OperatorAccount::getId).toList();
        long ledgerCount = lineIds.isEmpty() ? 0 : balanceRepository.countByOperatorAccountIdIn(lineIds);
        long lockedPeriodCount = lineIds.isEmpty() ? 0 : lockRepository.countByOperatorAccountIdIn(lineIds);
        if ((ledgerCount > 0 || lockedPeriodCount > 0) && !request.purgeHistory()) {
            throw ApiException.conflict("OPERATOR_HAS_HISTORY", "投放公司下存在历史台账或已结账期间，请确认清空后再删除",
                    Map.of("ledgerCount", ledgerCount, "lockedPeriodCount", lockedPeriodCount));
        }

        OperatorDtos.OperatorResponse before = operatorResponse(operator);
        if (lockedPeriodCount > 0) {
            lockRepository.deleteByOperatorAccountIdIn(lineIds);
            lockRepository.flush();
        }
        if (ledgerCount > 0) {
            balanceRepository.deleteByOperatorAccountIdIn(lineIds);
            balanceRepository.flush();
        }
        if (!lines.isEmpty()) {
            accountRepository.deleteAllInBatch(lines);
            accountRepository.flush();
        }
        operatorRepository.delete(operator);
        operatorRepository.flush();
        auditService.record("OPERATOR_DELETED", "OPERATOR", id.toString(), id, before,
                Map.of("deletedDeliveryLineCount", lineIds.size(), "purgedLedgerCount", ledgerCount,
                        "purgedLockedPeriodCount", lockedPeriodCount,
                        "reason", request.reason() == null ? "" : request.reason()));
    }

    @Transactional(readOnly = true)
    public List<OperatorDtos.AccountResponse> accounts(Long operatorId) {
        Operator company = requireOperator(operatorId);
        return accountRepository.findByOperatorIdOrderByAssetAscCodeAsc(operatorId).stream()
                .map(account -> accountResponse(account, company)).toList();
    }

    @Transactional
    public OperatorDtos.AccountResponse createAccount(Long operatorId, OperatorDtos.AccountRequest request) {
        Operator company = requireOperator(operatorId);
        String name = requiredName(request.name(), "投放线名称");
        ensureLineNameAvailable(operatorId, name, null);
        String asset = normalizeAsset(request.asset());
        OperatorAccount account = new OperatorAccount();
        account.setOperatorId(operatorId);
        account.setCode(requestedOrGeneratedLineCode(operatorId, request.code()));
        account.setName(name);
        account.setAsset(asset);
        // These are platform defaults, not editable per-line account settings
        // in the new UI.  Existing lines keep their historical values.
        account.setDefaultExchangeLossRate(DEFAULT_LINE_RATE);
        account.setDefaultExchangeLossBasis("TRANSFER");
        account.setDefaultServiceFeeRate(DEFAULT_LINE_RATE);
        account.setDefaultServiceFeeBasis("TRANSFER");
        account.setCalculationScale(2);
        applyAccountValues(account, request.network(), request.walletAddress(), request.startDate(),
                request.defaultExchangeLossRate(), request.defaultExchangeLossBasis(), request.defaultServiceFeeRate(),
                request.defaultServiceFeeBasis(), request.calculationScale(), false);
        account = accountRepository.save(account);
        OperatorDtos.AccountResponse result = accountResponse(account, company);
        auditService.record("OPERATOR_ACCOUNT_CREATED", "OPERATOR_ACCOUNT", account.getId().toString(), operatorId, null, result);
        return result;
    }

    @Transactional
    public OperatorDtos.AccountResponse patchAccount(Long accountId, OperatorDtos.AccountPatchRequest request) {
        OperatorAccount account = requireAccount(accountId);
        verifyVersion(account.getRowVersion(), request.rowVersion(), "ACCOUNT_VERSION_CONFLICT", "投放线已被其他人修改");
        OperatorDtos.AccountResponse before = accountResponse(account);
        if (request.name() != null && !request.name().isBlank()) {
            String name = requiredName(request.name(), "投放线名称");
            if (!sameName(account.getName(), name)) ensureLineNameAvailable(account.getOperatorId(), name, accountId);
            account.setName(name);
        }
        applyAccountValues(account, request.network(), request.walletAddress(), request.startDate(),
                request.defaultExchangeLossRate(), request.defaultExchangeLossBasis(), request.defaultServiceFeeRate(),
                request.defaultServiceFeeBasis(), request.calculationScale(), true);
        account = accountRepository.save(account);
        OperatorDtos.AccountResponse result = accountResponse(account);
        auditService.record("OPERATOR_ACCOUNT_UPDATED", "OPERATOR_ACCOUNT", accountId.toString(), account.getOperatorId(), before, result);
        return result;
    }

    @Transactional
    public OperatorDtos.AccountResponse disableAccount(Long accountId, OperatorDtos.DisableRequest request) {
        OperatorAccount account = requireAccount(accountId);
        verifyVersion(account.getRowVersion(), request.rowVersion(), "ACCOUNT_VERSION_CONFLICT", "投放线已被其他人修改");
        OperatorDtos.AccountResponse before = accountResponse(account);
        account.setStatus("INACTIVE");
        account = accountRepository.save(account);
        OperatorDtos.AccountResponse result = accountResponse(account);
        auditService.record("OPERATOR_ACCOUNT_DISABLED", "OPERATOR_ACCOUNT", accountId.toString(), account.getOperatorId(), before,
                Map.of("result", result, "reason", request.reason()));
        return result;
    }

    @Transactional(readOnly = true)
    public OperatorAccount requireAccount(Long accountId) {
        OperatorAccount account = accountRepository.findById(accountId).orElseThrow(() -> ApiException.notFound("投放线"));
        accessService.requireAccess(account.getOperatorId());
        return account;
    }

    @Transactional(readOnly = true)
    public Operator requireOperator(Long id) {
        Operator operator = operatorRepository.findById(id).orElseThrow(() -> ApiException.notFound("投放公司"));
        accessService.requireAccess(id);
        return operator;
    }

    @Transactional(readOnly = true)
    public Optional<Operator> findAccessibleOperatorByCodeOrName(String candidate) {
        Optional<Operator> operator = operatorRepository.findByCodeIgnoreCase(candidate)
                .or(() -> operatorRepository.findFirstByNameIgnoreCase(candidate));
        operator.ifPresent(value -> accessService.requireAccess(value.getId()));
        return operator;
    }

    @Transactional(readOnly = true)
    public Optional<OperatorAccount> findAccessibleAccount(Long operatorId, String accountCode) {
        accessService.requireAccess(operatorId);
        return accountRepository.findFirstByOperatorIdAndCodeIgnoreCase(operatorId, accountCode)
                .or(() -> accountRepository.findFirstByOperatorIdAndNameIgnoreCase(operatorId, accountCode));
    }

    private void applyAccountValues(OperatorAccount account, String network, String walletAddress, java.time.LocalDate startDate,
                                    BigDecimal exchangeRate, String exchangeBasis, BigDecimal serviceRate, String serviceBasis,
                                    Integer scale, boolean patch) {
        if (!patch || network != null) account.setNetwork(trimToNull(network));
        if (!patch || walletAddress != null) account.setWalletAddress(trimToNull(walletAddress));
        if (!patch || startDate != null) account.setStartDate(startDate);
        if (exchangeRate != null) account.setDefaultExchangeLossRate(validateRate(exchangeRate, "默认汇损率"));
        if (exchangeBasis != null) account.setDefaultExchangeLossBasis(validateBasis(exchangeBasis));
        if (serviceRate != null) account.setDefaultServiceFeeRate(validateRate(serviceRate, "默认服务费率"));
        if (serviceBasis != null) account.setDefaultServiceFeeBasis(validateBasis(serviceBasis));
        if (scale != null) {
            if (scale < 0 || scale > 8) throw ApiException.badRequest("INVALID_CALCULATION_SCALE", "计算精度必须在 0 到 8 之间");
            account.setCalculationScale(scale);
        }
    }

    private BigDecimal validateRate(BigDecimal rate, String field) {
        DecimalUtils.requireNonNegative(field, rate);
        if (rate.compareTo(BigDecimal.ONE) > 0) throw ApiException.badRequest("INVALID_RATE", field + "不得大于 1；2% 请传 0.02");
        return rate;
    }
    private String validateBasis(String basis) {
        String normalized = basis.trim().toUpperCase(Locale.ROOT);
        if (!BASES.contains(normalized)) throw ApiException.badRequest("INVALID_CALCULATION_BASIS", "不支持的计算基数");
        return normalized;
    }
    private String normalizeOperatorType(String type) {
        if (type == null || type.isBlank()) return "COMPANY";
        String normalized = type.trim().toUpperCase(Locale.ROOT);
        if (!OPERATOR_TYPES.contains(normalized)) throw ApiException.badRequest("INVALID_OPERATOR_TYPE", "投放公司类型不合法");
        return normalized;
    }
    private String normalizeAsset(String asset) {
        String normalized = asset == null || asset.isBlank() ? "USDT" : asset.trim().toUpperCase(Locale.ROOT);
        if (!ASSETS.contains(normalized)) throw ApiException.badRequest("INVALID_ASSET", "币种仅支持 USDT 或 USDC");
        return normalized;
    }
    private String requiredName(String value, String field) {
        String normalized = trimToNull(value);
        if (normalized == null) throw ApiException.badRequest("NAME_REQUIRED", field + "不能为空");
        return normalized;
    }
    private boolean sameName(String left, String right) {
        return normalizeName(left).equals(normalizeName(right));
    }
    private String normalizeName(String value) { return value == null ? "" : value.trim().toLowerCase(Locale.ROOT); }
    private void ensureCompanyNameAvailable(String name, Long exceptId) {
        boolean exists = operatorRepository.findAll().stream()
                .anyMatch(item -> !Objects.equals(item.getId(), exceptId) && sameName(item.getName(), name));
        if (exists) throw ApiException.conflict("COMPANY_NAME_EXISTS", "投放公司名称已存在");
    }
    private void ensureLineNameAvailable(Long operatorId, String name, Long exceptId) {
        boolean exists = accountRepository.findByOperatorIdOrderByAssetAscCodeAsc(operatorId).stream()
                .anyMatch(item -> !Objects.equals(item.getId(), exceptId) && sameName(item.getName(), name));
        if (exists) throw ApiException.conflict("DELIVERY_LINE_NAME_EXISTS", "该投放公司下投放线名称已存在");
    }
    private String nextOperatorCode() {
        String code;
        do { code = "COMP-" + UUID.randomUUID().toString().replace("-", "").toUpperCase(Locale.ROOT); }
        while (operatorRepository.existsByCodeIgnoreCase(code));
        return code;
    }
    private String nextLineCode(Long operatorId) {
        String code;
        do { code = "LINE-" + UUID.randomUUID().toString().replace("-", "").toUpperCase(Locale.ROOT); }
        while (accountRepository.findFirstByOperatorIdAndCodeIgnoreCase(operatorId, code).isPresent());
        return code;
    }
    private String requestedOrGeneratedCompanyCode(String requestedCode) {
        String code = trimToNull(requestedCode);
        if (code == null) return nextOperatorCode();
        code = code.toUpperCase(Locale.ROOT);
        if (operatorRepository.existsByCodeIgnoreCase(code)) {
            throw ApiException.conflict("OPERATOR_CODE_EXISTS", "投放公司编码已存在");
        }
        return code;
    }
    private String requestedOrGeneratedLineCode(Long operatorId, String requestedCode) {
        String code = trimToNull(requestedCode);
        if (code == null) return nextLineCode(operatorId);
        code = code.toUpperCase(Locale.ROOT);
        if (accountRepository.findFirstByOperatorIdAndCodeIgnoreCase(operatorId, code).isPresent()) {
            throw ApiException.conflict("ACCOUNT_CODE_EXISTS", "该投放公司下投放线编码已存在");
        }
        return code;
    }
    private String trimToNull(String value) { return value == null || value.isBlank() ? null : value.trim(); }
    private void verifyVersion(Long actual, Long request, String code, String message) {
        if (request != null && !Objects.equals(actual, request)) throw ApiException.conflict(code, message);
    }
    public OperatorDtos.OperatorResponse operatorResponse(Operator operator) {
        return new OperatorDtos.OperatorResponse(operator.getId(), operator.getCode(), operator.getName(), operator.getOperatorType(),
                operator.getStatus(), operator.getContactName(), operator.getContactValue(), operator.getRemark(), operator.getRowVersion(),
                operator.getCreatedAt(), operator.getUpdatedAt());
    }
    public OperatorDtos.AccountResponse accountResponse(OperatorAccount account) {
        Operator company = operatorRepository.findById(account.getOperatorId()).orElse(null);
        return accountResponse(account, company);
    }
    private OperatorDtos.AccountResponse accountResponse(OperatorAccount account, Operator company) {
        String companyName = company == null ? null : company.getName();
        String displayName = companyName == null || companyName.isBlank() ? account.getName() : companyName + " · " + account.getName();
        return new OperatorDtos.AccountResponse(account.getId(), account.getOperatorId(), companyName, displayName,
                account.getCode(), account.getName(), account.getAsset(),
                account.getNetwork(), account.getWalletAddress(), account.getStartDate(), account.getDefaultExchangeLossRate(),
                account.getDefaultExchangeLossBasis(), account.getDefaultServiceFeeRate(), account.getDefaultServiceFeeBasis(),
                account.getCalculationScale(), account.getStatus(), account.getRowVersion());
    }
}
