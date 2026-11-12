package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;
import com.rajads.erp.audit.AuditService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.*;

/** Draft checks do not create tasks or change remote data. Remote reads are explicitly opt-in. */
@Service
@RequiredArgsConstructor
public class RedemptionDuplicateCheckService {
    private final NamedParameterJdbcTemplate jdbc;
    private final RedemptionCodeIssueRepository issues;
    private final RedemptionCodeBatchRepository batches;
    private final RedemptionRemoteDirectory directory;
    private final ObjectProvider<UnifiedRedemptionRemoteExecutorClient> executor;
    private final AuditService audit;
    private final ObjectMapper mapper;
    private static final String TASK_REVIEW_ACTION = "REDEMPTION_TASK_DUPLICATES_CONFIRMED";

    public record MarketRequest(@NotNull @Min(1) Long marketId,
                                @NotNull RedemptionCodeType redemptionType,
                                @NotNull LocalDate from, @NotNull LocalDate to,
                                @NotEmpty @Size(max=50) List<@NotNull @DecimalMin("0") BigDecimal> deposits,
                                RedemptionCodeNaming specialCodeNaming) { }
    public record Request(@NotEmpty @Size(max=20) List<@Valid MarketRequest> markets, boolean checkRemote) { }
    public record Conflict(Long marketId, String code, String source, Long issueId, Long batchId,
                           String taskNumber, String configurationId, String localStatus,
                           BigDecimal localRewardMin, BigDecimal localRewardMax, String reviewFingerprint) { }
    public record Review(@NotNull Boolean confirmed,
                         @NotNull @Size(max=10000) Map<String, String> fingerprints) { }
    public record Result(int checkedCodes, boolean remoteChecked, List<Conflict> conflicts, boolean reviewConfirmed) {
        public Result(int checkedCodes, boolean remoteChecked, List<Conflict> conflicts) {
            this(checkedCodes, remoteChecked, conflicts, false);
        }
    }
    private record StoredReview(int version, Long taskId, Map<String, String> fingerprints) { }
    private record Key(Long marketId, String code) { }

    /** Resume reviews cover the persisted task, not the unrelated new-task form. Read-only and local. */
    public Result checkPendingTask(Long batchId) {
        var batch = batches.findById(batchId).orElseThrow(() -> ApiException.notFound("兑换码批次"));
        var members = batches.findByTaskIdOrderByIdAsc(batch.getTaskId());
        var byId = new HashMap<Long, RedemptionCodeBatch>();
        members.forEach(member -> byId.put(member.getId(), member));
        var wanted = new LinkedHashSet<Key>();
        for (var issue : issues.findByBatchIdInOrderByBatchIdAscClaimDateAscCampaignTierIdAsc(byId.keySet())) {
            var member = byId.get(issue.getBatchId());
            if (member.getRedemptionType() == null || !member.getRedemptionType().usesSpecialCode()
                    || !Objects.equals(member.getRemoteKeyNumber(), 1)
                    || issue.getReusedFromIssue() != null || RemoteConfigurationIds.isValid(issue.getRemoteConfigurationId())
                    || issue.getRemoteReferenceId() != null || issue.getRemoteCreateReceiptId() != null
                    || issue.getRemoteDeletionState() != null || RemoteConfigurationIds.needsReconciliation(issue)
                    || !Set.of("PENDING_CREATION", "FAILED").contains(Objects.toString(issue.getWorkflowStatus(), ""))) continue;
            wanted.add(new Key(issue.getRemoteMarketId(), member.specialCode(issue.getClaimDate(), issue.getMinDepositAmount()).toLowerCase(Locale.ROOT)));
        }
        var conflicts = localConflicts(wanted, null);
        return new Result(wanted.size(), false, conflicts, covers(savedReview(batch.getTaskId()), conflicts));
    }

    /** Append an immutable approval event. During group creation this joins the task's transaction. */
    @Transactional
    public void confirmTaskReview(Long batchId, Review review) {
        var batch = batches.findById(batchId).orElseThrow(() -> ApiException.notFound("兑换码批次"));
        var result = checkPendingTask(batchId);
        if (review == null || !Boolean.TRUE.equals(review.confirmed()) || !covers(review, result.conflicts()))
            throw ApiException.conflict("LOCAL_REDEMPTION_DUPLICATE", "同码记录已变化，请集中阅览新增或变化的记录后确认；未提交远端创建。");
        // Save only server-verified task conflicts; do not turn arbitrary client hashes into approval.
        var fingerprints = new LinkedHashMap<String, String>();
        var previous = savedReview(batch.getTaskId());
        if (previous != null) fingerprints.putAll(previous.fingerprints());
        result.conflicts().forEach(c -> fingerprints.put(c.issueId().toString(), c.reviewFingerprint()));
        audit.record(TASK_REVIEW_ACTION, "REDEMPTION_CODE_TASK", batch.getTaskId().toString(), null, null,
                new StoredReview(1, batch.getTaskId(), fingerprints));
    }

    private boolean covers(Review review, List<Conflict> conflicts) {
        return review != null && Boolean.TRUE.equals(review.confirmed()) && review.fingerprints() != null
                && conflicts.stream().allMatch(c -> Objects.equals(c.reviewFingerprint(), review.fingerprints().get(c.issueId().toString())));
    }

    private Review savedReview(Long taskId) {
        var records = jdbc.queryForList("""
                select after_json from erp_compat_audit_logs
                 where entity_type='REDEMPTION_CODE_TASK' and entity_id=:taskId and action=:action
                 order by id desc limit 1
                """, Map.of("taskId", taskId.toString(), "action", TASK_REVIEW_ACTION));
        if (records.isEmpty()) return null;
        try {
            var saved = mapper.readValue((String) records.getFirst().get("after_json"), StoredReview.class);
            if (saved.version() != 1 || !Objects.equals(saved.taskId(), taskId) || saved.fingerprints() == null) return null;
            return new Review(true, saved.fingerprints());
        } catch (java.io.IOException | RuntimeException ignored) { return null; }
    }

    public Result check(Request request) {
        var wanted = requestedCodes(request.markets());
        var conflicts = new ArrayList<>(localConflicts(wanted, null));
        if (request.checkRemote() && !wanted.isEmpty()) {
            var client = executor.getIfAvailable();
            if (client == null) throw ApiException.conflict("REMOTE_DUPLICATE_CHECK_UNAVAILABLE", "远端查重服务不可用，本次未创建配置");
            // One directory check per market, shared by every code in this draft.
            for (Long marketId : wanted.stream().map(Key::marketId).distinct().toList()) {
                var account = directory.selectEnabledForMarket(marketId);
                var codes = wanted.stream().filter(k -> k.marketId().equals(marketId)).map(Key::code).toList();
                for (var match : client.checkDuplicateCodes(account.id(), codes)) {
                    boolean alreadyListed = conflicts.stream().anyMatch(c -> c.marketId().equals(marketId)
                            && c.code().equalsIgnoreCase(match.code()) && Objects.equals(c.configurationId(), match.configurationId()));
                    if (!alreadyListed) conflicts.add(new Conflict(marketId, match.code(), "REMOTE", null,
                            null, null, match.configurationId(), null, null, null, null));
                }
            }
        }
        return new Result(wanted.size(), request.checkRemote() && !wanted.isEmpty(), List.copyOf(conflicts));
    }

    /** Recheck local facts at execution time, so bypassing or racing the draft preview cannot auto-reuse a code. */
    public void requireNoLocalDuplicate(Long issueId) {
        requireReviewedDuplicates(issueId, null);
    }

    public void requireReviewedDuplicates(Long issueId, Review review) {
        var issue = issues.findById(issueId).orElseThrow(() -> ApiException.notFound("兑换码任务"));
        if (issue.getReusedFromIssue() != null || RemoteConfigurationIds.isValid(issue.getRemoteConfigurationId())) return;
        if (issue.getBatchId() == null) return;
        var batch = batches.findById(issue.getBatchId()).orElseThrow(() -> ApiException.notFound("兑换码批次"));
        if (batch.getRedemptionType() == null || !batch.getRedemptionType().usesSpecialCode()
                || !Objects.equals(batch.getRemoteKeyNumber(), 1)) return;
        String code = batch.specialCode(issue.getClaimDate(), issue.getMinDepositAmount());
        var found = localConflicts(Set.of(new Key(issue.getRemoteMarketId(), code.toLowerCase(Locale.ROOT))), issueId);
        if (!found.isEmpty()) {
            if (covers(review == null ? savedReview(batch.getTaskId()) : review, found)) {
                audit.record("REDEMPTION_DUPLICATES_REVIEW_CONFIRMED", "REDEMPTION_CODE_ISSUE", issueId.toString(),
                        null, found, Map.of("code", code, "reviewed", true, "remoteDeletionInferred", false));
                return;
            }
            var first = found.getFirst();
            throw ApiException.conflict("LOCAL_REDEMPTION_DUPLICATE", "本地已有同码 " + code
                    + "，关联任务 " + Objects.requireNonNullElse(first.taskNumber(), "未编号")
                    + "、配置 " + Objects.requireNonNullElse(first.configurationId(), "结果待核对")
                    + "。请阅读同码提示并确认继续创建；历史记录不代表远端配置仍存在，记录变化后需要重新确认。");
        }
    }

    private Set<Key> requestedCodes(List<MarketRequest> requests) {
        var result = new LinkedHashSet<Key>();
        for (var request : requests) {
            long days = ChronoUnit.DAYS.between(request.from(), request.to());
            if (days < 0 || days > 365) throw ApiException.badRequest("INVALID_DATE_RANGE", "查重日期范围须在 366 天以内");
            if (!request.redemptionType().usesSpecialCode()) continue;
            for (LocalDate date = request.from(); !date.isAfter(request.to()); date = date.plusDays(1)) {
                for (var deposit : request.deposits()) {
                    var key = new Key(request.marketId(), request.redemptionType().specialCode(date, deposit, request.specialCodeNaming()).toLowerCase(Locale.ROOT));
                    if (!result.add(key)) throw ApiException.badRequest("DUPLICATE_SPECIAL_CODE", "本次任务内包含重复的特殊兑换码：" + key.code());
                    if (result.size() > 10000) throw ApiException.badRequest("DUPLICATE_CHECK_TOO_LARGE", "单次查重最多支持 10000 个兑换码");
                }
            }
        }
        return result;
    }

    private List<Conflict> localConflicts(Set<Key> wanted, Long excludedIssue) {
        if (wanted.isEmpty()) return List.of();
        var params = Map.of("markets", wanted.stream().map(Key::marketId).distinct().toList(),
                "codes", wanted.stream().map(Key::code).distinct().toList());
        // Scalar rows avoid loading inventories and shared-task graphs. No remote registry/session is accessed.
        var rows = jdbc.queryForList("""
                select i.id, i.remote_market_id, i.batch_id, i.claim_date, i.min_deposit_amount,
                       i.redemption_code, c.code as stored_code, i.remote_configuration_id,
                       i.workflow_status, i.remote_error, i.remote_group_key, i.remote_deletion_state, i.bonus_amount, i.bonus_max_amount,
                       b.redemption_type, b.special_code_naming, b.remote_key_number, t.task_date, t.daily_sequence
                  from erp_compat_redemption_code_issues i
                  left join erp_compat_redemption_code_batches b on b.id=i.batch_id
                  left join erp_compat_redemption_code_tasks t on t.id=b.task_id
                  left join erp_compat_redemption_issue_codes c on c.issue_id=i.id
                 where i.remote_market_id in (:markets) and i.reused_from_issue_id is null
                   and (lower(i.redemption_code) in (:codes) or lower(c.code) in (:codes)
                        or (i.redemption_code is null and c.code is null and b.remote_key_number=1
                            and b.redemption_type in ('SEVEN_DAY_DEPOSIT','PREVIOUS_DAY_DEPOSIT')))
                   and (i.remote_configuration_id is not null or i.remote_create_receipt_id is not null
                        or i.remote_reference_id is not null or i.redemption_code is not null or c.code is not null
                        or i.workflow_status='CREATING_REMOTE' or i.remote_deletion_state is not null
                        or i.remote_error like '远端创建结果未确认%')
                 order by i.id
                """, params);
        var matches = new LinkedHashMap<String, Conflict>();
        for (var row : rows) {
            Long id = number(row, "id");
            if (Objects.equals(id, excludedIssue)) continue;
            var codes = new LinkedHashSet<String>();
            if (row.get("redemption_code") != null) codes.add(row.get("redemption_code").toString());
            if (row.get("stored_code") != null) codes.add(row.get("stored_code").toString());
            if (codes.isEmpty() && Objects.equals(number(row, "remote_key_number"), 1L) && row.get("redemption_type") != null) {
                var type = RedemptionCodeType.valueOf(row.get("redemption_type").toString());
                if (type.usesSpecialCode()) codes.add(type.specialCode(date(row, "claim_date"), (BigDecimal) row.get("min_deposit_amount"),
                        RedemptionCodeNaming.valueOf(Objects.toString(row.get("special_code_naming"), "ORIGINAL"))));
            }
            Long marketId = number(row, "remote_market_id");
            for (String raw : codes) {
                String code = raw.toLowerCase(Locale.ROOT);
                if (!wanted.contains(new Key(marketId, code))) continue;
                String task = row.get("task_date") == null ? null : date(row, "task_date").format(DateTimeFormatter.BASIC_ISO_DATE)
                        + String.format(Locale.ROOT, "%04d", number(row, "daily_sequence"));
                String state = (String) row.get("remote_deletion_state");
                matches.putIfAbsent(id + ":" + code, new Conflict(marketId, code, "LOCAL", id, number(row, "batch_id"),
                        task, (String) row.get("remote_configuration_id"), state != null ? state : (String) row.get("workflow_status"),
                        (BigDecimal) row.get("bonus_amount"), (BigDecimal) row.get("bonus_max_amount"),
                        fingerprint("v2:" + id + ":" + marketId + ":" + code + ":" + row.get("remote_configuration_id") + ":" + row.get("remote_group_key")
                                + ":" + ("CREATING_REMOTE".equals(row.get("workflow_status"))
                                    || Objects.toString(row.get("remote_error"), "").contains(RemoteConfigurationIds.UNCONFIRMED_PREFIX))
                                + ":" + row.get("remote_deletion_state")
                                + ":" + row.get("bonus_amount") + ":" + row.get("bonus_max_amount"))));
            }
        }
        return List.copyOf(matches.values());
    }

    private static Long number(Map<String, Object> row, String key) { return row.get(key) instanceof Number n ? n.longValue() : null; }
    private static String fingerprint(String value) {
        try { return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private static LocalDate date(Map<String, Object> row, String key) { return LocalDate.parse(row.get(key).toString()); }
}
