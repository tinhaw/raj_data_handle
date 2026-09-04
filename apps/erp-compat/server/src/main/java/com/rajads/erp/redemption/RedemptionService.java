package com.rajads.erp.redemption;

import com.rajads.erp.audit.AuditService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.shared.ApiException;
import com.rajads.erp.shared.DecimalUtils;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.*;

@Service
@RequiredArgsConstructor
public class RedemptionService {
    private static final Set<String> CAMPAIGN_STATUSES = Set.of("DRAFT", "ACTIVE", "ARCHIVED");
    private final RedemptionCampaignRepository campaignRepository;
    private final RedemptionCampaignTierRepository tierRepository;
    private final RedemptionCodeBatchRepository batchRepository;
    private final RedemptionCodeTaskRepository taskRepository;
    private final RedemptionCodeIssueRepository issueRepository;
    private final RedemptionRemoteDirectory remoteDirectory;
    private final ObjectMapper objectMapper;
    private final CurrentUser currentUser;
    private final AuditService auditService;
    private final RedemptionCodeStorage codeStorage;

    @Transactional(readOnly = true)
    public List<RedemptionDtos.CampaignResponse> campaigns() {
        return campaignRepository.findAllByOrderByCreatedAtDesc().stream().map(this::campaignResponse).toList();
    }

    @Transactional(readOnly = true)
    public RedemptionDtos.CampaignResponse campaign(Long id) { return campaignResponse(requireCampaign(id)); }

    @Transactional
    public RedemptionDtos.CampaignResponse create(RedemptionDtos.CampaignRequest request) {
        String code = normalizeCode(request.code());
        if (campaignRepository.findByCodeIgnoreCase(code).isPresent()) {
            throw ApiException.conflict("CAMPAIGN_CODE_EXISTS", "活动编码已存在");
        }
        RedemptionCampaign campaign = new RedemptionCampaign();
        campaign.setCode(code);
        campaign.setName(requiredText(request.name(), "活动名称"));
        campaign.setLookbackDays(request.lookbackDays() == null ? 7 : request.lookbackDays());
        campaign.setDescription(trimToNull(request.description()));
        campaign.setCreatedBy(currentUser.require().id());
        campaign.setUpdatedBy(currentUser.require().id());
        campaign = campaignRepository.save(campaign);
        replaceTiers(campaign.getId(), request.tiers());
        RedemptionDtos.CampaignResponse result = campaignResponse(campaign);
        auditService.record("REDEMPTION_CAMPAIGN_CREATED", "REDEMPTION_CAMPAIGN", campaign.getId().toString(), null, null,
                auditCampaignSummary(result));
        return result;
    }

    @Transactional
    public RedemptionDtos.CampaignResponse patch(Long id, RedemptionDtos.CampaignPatchRequest request) {
        RedemptionCampaign campaign = requireCampaign(id);
        verifyVersion(campaign.getRowVersion(), request.rowVersion());
        RedemptionDtos.CampaignResponse before = campaignResponse(campaign);
        if (request.name() != null) campaign.setName(requiredText(request.name(), "活动名称"));
        if (request.status() != null) campaign.setStatus(normalizeStatus(request.status()));
        if (request.lookbackDays() != null) campaign.setLookbackDays(request.lookbackDays());
        if (request.description() != null) campaign.setDescription(trimToNull(request.description()));
        if (request.tiers() != null) {
            if (issueRepository.existsByCampaignId(id)) {
                throw ApiException.conflict("CAMPAIGN_TIER_LOCKED", "该活动已有兑换码记录；为保证历史快照，不能再修改充值分档");
            }
            tierRepository.deleteByCampaignId(id);
            tierRepository.flush();
            replaceTiers(id, request.tiers());
        }
        campaign.setUpdatedBy(currentUser.require().id());
        campaign = campaignRepository.save(campaign);
        RedemptionDtos.CampaignResponse result = campaignResponse(campaign);
        auditService.record("REDEMPTION_CAMPAIGN_UPDATED", "REDEMPTION_CAMPAIGN", id.toString(), null,
                auditCampaignSummary(before), auditCampaignSummary(result));
        return result;
    }

    @Transactional(readOnly = true)
    public List<RedemptionDtos.CodeIssueResponse> issues(Long campaignId, LocalDate claimDateFrom, LocalDate claimDateTo) {
        requireRange(claimDateFrom, claimDateTo, 366, "查询");
        requireCampaign(campaignId);
        return issueRepository.findByCampaignIdAndClaimDateBetweenOrderByClaimDateAscCampaignTierIdAsc(campaignId, claimDateFrom, claimDateTo)
                .stream().map(this::issueResponse).toList();
    }

    @Transactional(readOnly = true)
    public List<RedemptionDtos.BatchResponse> batches(Long campaignId) {
        requireCampaign(campaignId);
        return batchRepository.findByCampaignIdOrderByCreatedAtDesc(campaignId).stream().map(this::batchResponse).toList();
    }

    @Transactional(readOnly = true)
    public RedemptionDtos.BatchDetailResponse batch(Long batchId) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        requireCampaign(batch.getCampaignId());
        return batchDetail(batch);
    }

    /** Create the campaign and its first remote batch together for the code-group generation screen. */
    @Transactional
    public RedemptionDtos.BatchDetailResponse createCodeGroup(RedemptionDtos.CodeGroupCreateRequest request) {
        RedemptionRemoteDirectory.Account selectedConnection = remoteDirectory.selectEnabledForMarket(request.remoteMarketId());
        RedemptionCodeType redemptionType = request.redemptionType() == null ? RedemptionCodeType.SEVEN_DAY_DEPOSIT : request.redemptionType();
        RedemptionCodeTask task = resolveTask(request.exportGroupKey());
        List<List<Long>> requestedTierLabelIds = normalizeTierLabelIds(request, redemptionType);
        remoteDirectory.requireCurrentTags(selectedConnection.id(), requestedTierLabelIds.stream()
                .filter(Objects::nonNull).flatMap(Collection::stream).filter(Objects::nonNull).toList());
        int lookbackDays = redemptionType == RedemptionCodeType.PREVIOUS_DAY_DEPOSIT ? 1 : request.lookbackDays();
        RedemptionDtos.CampaignResponse created = create(new RedemptionDtos.CampaignRequest(
                request.code(), request.name(), lookbackDays, request.description(), request.tiers()));
        RedemptionCampaign campaign = requireCampaign(created.id());
        campaign.setStatus("ACTIVE");
        campaign.setUpdatedBy(currentUser.require().id());
        campaignRepository.save(campaign);

        List<RedemptionCampaignTier> createdTiers = tierRepository.findByCampaignIdOrderBySortOrderAscMinDepositAmountAsc(campaign.getId());
        if (requestedTierLabelIds.size() != createdTiers.size()) {
            throw ApiException.badRequest("INVALID_TIER_AUDIENCES", "每个充值档位都必须提供一个用户类型");
        }
        Map<Long, List<Long>> tierLabelIds = new LinkedHashMap<>();
        for (int index = 0; index < createdTiers.size(); index++) {
            RedemptionCampaignTier tier = createdTiers.get(index);
            tierLabelIds.put(tier.getId(), requestedTierLabelIds.get(index));
        }
        RedemptionDtos.BatchDetailResponse detail = createManualBatch(new RedemptionDtos.ManualBatchCreateRequest(
                campaign.getId(), request.claimDateFrom(), request.claimDateTo(),
                request.validFromDayOffset(), request.validToDayOffset(), selectedConnection.id(),
                tierLabelIds, request.remoteOptions(), redemptionType), task.getId());
        if (request.exportGroupKey() != null && !request.exportGroupKey().isBlank()) {
            RedemptionCodeBatch batch = requireBatch(detail.batch().id());
            batch.setExportGroupKey(request.exportGroupKey().trim());
            batchRepository.save(batch);
            detail = batchDetail(batch);
        }
        auditService.record("REDEMPTION_CODE_GROUP_CREATED", "REDEMPTION_CODE_BATCH", detail.batch().id().toString(), null, null,
                Map.of("campaignCode", campaign.getCode(), "claimDateFrom", request.claimDateFrom().toString(),
                        "claimDateTo", request.claimDateTo().toString(), "expectedCodeCount", detail.batch().expectedCodeCount(),
                        "redemptionType", redemptionType.name(), "remoteMarketId", request.remoteMarketId(),
                        "remoteConnectionId", selectedConnection.id()));
        return detail;
    }

    /**
     * Creates the local checklist for a manual remote-backend operation.  It
     * does not contact the remote system and consequently cannot create a
     * redeemable code on its own.
     */
    @Transactional
    public RedemptionDtos.BatchDetailResponse createManualBatch(RedemptionDtos.ManualBatchCreateRequest request) {
        return createManualBatch(request, createStandaloneTask().getId());
    }

    private RedemptionDtos.BatchDetailResponse createManualBatch(RedemptionDtos.ManualBatchCreateRequest request, Long taskId) {
        requireRange(request.claimDateFrom(), request.claimDateTo(), 366, "创建批次");
        int validFromDayOffset = request.validFromDayOffset() == null ? 0 : request.validFromDayOffset();
        int validToDayOffset = request.validToDayOffset() == null ? 0 : request.validToDayOffset();
        requireValidityOffsets(validFromDayOffset, validToDayOffset);
        RedemptionCampaign campaign = requireCampaign(request.campaignId());
        RedemptionCodeType redemptionType = request.redemptionType() == null ? RedemptionCodeType.SEVEN_DAY_DEPOSIT : request.redemptionType();
        if (!"ACTIVE".equals(campaign.getStatus())) {
            throw ApiException.conflict("CAMPAIGN_NOT_ACTIVE", "请先将活动设为“进行中”，再创建人工兑换码批次");
        }
        if (issueRepository.existsByCampaignIdAndClaimDateBetween(campaign.getId(), request.claimDateFrom(), request.claimDateTo())) {
            throw ApiException.conflict("CLAIM_DATE_ALREADY_BATCHED", "所选领取日期已有兑换码任务，不能重复创建批次");
        }
        List<RedemptionCampaignTier> tiers = tierRepository.findByCampaignIdOrderBySortOrderAscMinDepositAmountAsc(campaign.getId());
        if (tiers.isEmpty()) throw ApiException.badRequest("CAMPAIGN_TIER_REQUIRED", "活动至少需要一个充值分档");
        RedemptionRemoteDirectory.Account remoteConnection = null;
        Map<Long, List<Long>> tierLabelIds = request.tierLabelIds() == null ? Map.of() : request.tierLabelIds();
        if (request.remoteConnectionId() != null) {
            remoteConnection = remoteDirectory.requireEnabled(request.remoteConnectionId());
            for (RedemptionCampaignTier tier : tiers) validateLabelIds(redemptionType, tier, tierLabelIds.get(tier.getId()));
        }
        int dates = Math.toIntExact(ChronoUnit.DAYS.between(request.claimDateFrom(), request.claimDateTo()) + 1);
        RedemptionCodeBatch batch = new RedemptionCodeBatch();
        batch.setCampaignId(campaign.getId());
        batch.setClaimDateFrom(request.claimDateFrom());
        batch.setClaimDateTo(request.claimDateTo());
        batch.setValidFromDayOffset(validFromDayOffset);
        batch.setValidToDayOffset(validToDayOffset);
        batch.setLookbackDays(campaign.getLookbackDays());
        batch.setRedemptionType(redemptionType);
        batch.setExpectedCodeCount(Math.multiplyExact(dates, tiers.size()));
        batch.setRemoteConnectionId(remoteConnection == null ? null : remoteConnection.id());
        batch.setTaskId(taskId);
        if (remoteConnection != null) applyRemoteOptions(batch, request.remoteOptions());
        batch.setCreatedBy(currentUser.require().id());
        batch = batchRepository.save(batch);

        List<RedemptionCodeIssue> tasks = new ArrayList<>();
        for (LocalDate date = request.claimDateFrom(); !date.isAfter(request.claimDateTo()); date = date.plusDays(1)) {
            for (RedemptionCampaignTier tier : tiers) {
                RedemptionCodeIssue issue = newIssue(campaign, tier, date);
                issue.setBatchId(batch.getId());
                issue.setWorkflowStatus("PENDING_CREATION");
                if (remoteConnection != null) issue.setRemoteLabelIdsJson(serializeLabelIds(tierLabelIds.get(tier.getId())));
                tasks.add(issue);
            }
        }
        issueRepository.saveAll(tasks);
        auditService.record("REDEMPTION_MANUAL_BATCH_CREATED", "REDEMPTION_CODE_BATCH", batch.getId().toString(), null, null,
                Map.of("campaignCode", campaign.getCode(), "claimDateFrom", request.claimDateFrom().toString(),
                        "claimDateTo", request.claimDateTo().toString(), "expectedCodeCount", batch.getExpectedCodeCount(),
                        "remoteConnectionId", batch.getRemoteConnectionId() == null ? "" : batch.getRemoteConnectionId().toString()));
        return batchDetail(batch);
    }

    @Transactional
    public RedemptionDtos.BatchDetailResponse recordRemoteConfiguration(Long issueId, RedemptionDtos.RemoteConfigurationRequest request) {
        RedemptionCodeIssue issue = requireIssue(issueId);
        RedemptionCodeBatch batch = requireManualBatch(issue);
        verifyVersion(issue.getRowVersion(), request.rowVersion(), "CODE_TASK_VERSION_CONFLICT", "兑换码任务已被其他人修改，请刷新后重试");
        if (!"PENDING_CREATION".equals(issue.getWorkflowStatus()) && !"CREATED".equals(issue.getWorkflowStatus())) {
            throw ApiException.conflict("REMOTE_CONFIGURATION_LOCKED", "该任务已经发布或已导入兑换码，不能修改远端配置 ID");
        }
        String remoteConfigurationId = requiredText(request.remoteConfigurationId(), "远端兑换码配置 ID");
        issueRepository.findByRemoteConfigurationId(remoteConfigurationId).ifPresent(other -> {
            if (!Objects.equals(other.getId(), issue.getId())) {
                throw ApiException.conflict("REMOTE_CONFIGURATION_ID_EXISTS", "该远端兑换码配置 ID 已登记到其他任务");
            }
        });
        issue.setRemoteConfigurationId(remoteConfigurationId);
        issue.setWorkflowStatus("CREATED");
        issueRepository.save(issue);
        refreshBatchStatus(batch);
        auditService.record("REDEMPTION_REMOTE_CONFIGURATION_RECORDED", "REDEMPTION_CODE_ISSUE", issue.getId().toString(), null, null,
                Map.of("batchId", batch.getId(), "claimDate", issue.getClaimDate().toString(), "tierId", issue.getCampaignTierId()));
        return batchDetail(batch);
    }

    @Transactional
    public RedemptionDtos.BatchDetailResponse markBatchPublished(Long batchId, RedemptionDtos.PublishBatchRequest request) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        verifyVersion(batch.getRowVersion(), request.rowVersion(), "BATCH_VERSION_CONFLICT", "批次已被其他人修改，请刷新后重试");
        if (!"READY_TO_PUBLISH".equals(batch.getStatus())) {
            throw ApiException.conflict("BATCH_NOT_READY_TO_PUBLISH", "请先在远端逐条创建并登记全部兑换码配置，再确认发布");
        }
        List<RedemptionCodeIssue> issues = issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batchId);
        if (issues.size() != batch.getExpectedCodeCount() || issues.stream().anyMatch(issue -> !"CREATED".equals(issue.getWorkflowStatus()))) {
            throw ApiException.conflict("BATCH_NOT_READY_TO_PUBLISH", "该批次仍有未完成创建的远端兑换码配置");
        }
        issues.forEach(issue -> issue.setWorkflowStatus("PUBLISHED"));
        issueRepository.saveAll(issues);
        batch.setStatus("PUBLISHED");
        batch.setPublishedAt(Instant.now());
        batch.setPublishedBy(currentUser.require().id());
        batchRepository.save(batch);
        auditService.record("REDEMPTION_BATCH_PUBLISHED_CONFIRMED", "REDEMPTION_CODE_BATCH", batch.getId().toString(), null, null,
                Map.of("expectedCodeCount", batch.getExpectedCodeCount()));
        return batchDetail(batch);
    }

    @Transactional
    public RedemptionDtos.CodeImportResponse importDownloadedCodes(Long batchId, RedemptionDtos.CodeImportRequest request) {
        RedemptionCodeBatch batch = requireBatch(batchId);
        if (!Set.of("PUBLISHED", "COMPLETED").contains(batch.getStatus())) {
            throw ApiException.conflict("BATCH_NOT_PUBLISHED", "请先在远端发布全部兑换码，再下载并导入兑换码");
        }
        Map<String, List<String>> groupedCodes = new LinkedHashMap<>();
        Set<String> codes = new LinkedHashSet<>();
        for (RedemptionDtos.CodeImportRow row : request.rows()) {
            String configId = requiredText(row.remoteConfigurationId(), "远端兑换码配置 ID");
            String code = requiredText(row.redemptionCode(), "兑换码");
            groupedCodes.computeIfAbsent(configId, ignored -> new ArrayList<>()).add(code);
            if (!codes.add(code)) throw ApiException.badRequest("DUPLICATE_REDEMPTION_CODE", "导入内容包含重复的兑换码");
        }
        Set<String> configurationIds = groupedCodes.keySet();
        List<RedemptionCodeIssue> issues = issueRepository.findByBatchIdAndRemoteConfigurationIdIn(batchId, configurationIds);
        if (issues.size() != configurationIds.size()) {
            throw ApiException.badRequest("UNKNOWN_REMOTE_CONFIGURATION_ID", "导入内容中存在不属于该批次或尚未登记的远端配置 ID");
        }
        Map<String, RedemptionCodeIssue> byConfig = new HashMap<>();
        issues.forEach(issue -> byConfig.put(issue.getRemoteConfigurationId(), issue));
        int imported = 0;
        for (Map.Entry<String, List<String>> entry : groupedCodes.entrySet()) {
            RedemptionCodeIssue issue = byConfig.get(entry.getKey());
            if (!Set.of("PUBLISHED", "CODE_IMPORTED").contains(issue.getWorkflowStatus())) {
                throw ApiException.conflict("CODE_TASK_NOT_PUBLISHED", "存在尚未发布的兑换码任务，不能导入");
            }
            imported += codeStorage.store(issue, batch, entry.getValue());
            issue.setWorkflowStatus("CODE_IMPORTED");
            issue.setState("GENERATED");
            issue.setGeneratedAt(Instant.now());
            issue.setRemoteError(null);
        }
        issueRepository.saveAll(issues);
        batch = refreshBatchStatus(batch);
        List<RedemptionDtos.CodeIssueResponse> resultIssues = issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batchId)
                .stream().map(this::issueResponse).toList();
        auditService.record("REDEMPTION_CODES_IMPORTED", "REDEMPTION_CODE_BATCH", batchId.toString(), null, null,
                Map.of("importedCount", imported, "submittedRowCount", request.rows().size()));
        return new RedemptionDtos.CodeImportResponse(imported, batchResponse(batch), resultIssues);
    }

    private RedemptionCodeIssue newIssue(RedemptionCampaign campaign, RedemptionCampaignTier tier, LocalDate claimDate) {
        RedemptionCodeIssue issue = new RedemptionCodeIssue();
        issue.setCampaignId(campaign.getId());
        issue.setCampaignTierId(tier.getId());
        issue.setClaimDate(claimDate);
        issue.setDepositWindowStart(claimDate.minusDays(campaign.getLookbackDays()));
        issue.setDepositWindowEnd(claimDate.minusDays(1));
        issue.setTierName(trimToNull(tier.getDisplayName()));
        issue.setMinDepositAmount(tier.getMinDepositAmount());
        issue.setBonusAmount(tier.getBonusAmount());
        issue.setBonusMaxAmount(tier.getBonusMaxAmount());
        issue.setRemoteRequestId(UUID.randomUUID().toString());
        issue.setCreatedBy(currentUser.require().id());
        return issue;
    }

    private void replaceTiers(Long campaignId, List<RedemptionDtos.TierRequest> requests) {
        if (requests == null || requests.isEmpty()) throw ApiException.badRequest("CAMPAIGN_TIER_REQUIRED", "活动至少需要一个充值分档");
        if (requests.size() > 20) throw ApiException.badRequest("TOO_MANY_CAMPAIGN_TIERS", "一个活动最多配置 20 个充值分档");
        Set<BigDecimal> deposits = new HashSet<>();
        List<RedemptionCampaignTier> tiers = new ArrayList<>();
        for (int index = 0; index < requests.size(); index++) {
            RedemptionDtos.TierRequest request = requests.get(index);
            BigDecimal deposit = normalizedAmount(request.minDepositAmount(), "充值门槛");
            if (!deposits.add(deposit.stripTrailingZeros())) {
                throw ApiException.badRequest("DUPLICATE_DEPOSIT_TIER", "充值门槛不能重复");
            }
            RedemptionCampaignTier tier = new RedemptionCampaignTier();
            tier.setCampaignId(campaignId);
            tier.setDisplayName(trimToNull(request.displayName()));
            tier.setMinDepositAmount(deposit);
            tier.setBonusAmount(normalizedAmount(request.bonusAmount(), "赠金金额"));
            BigDecimal maxBonus = request.bonusMaxAmount() == null ? tier.getBonusAmount()
                    : normalizedAmount(request.bonusMaxAmount(), "最大奖金金额");
            if (maxBonus.compareTo(tier.getBonusAmount()) < 0) {
                throw ApiException.badRequest("INVALID_BONUS_RANGE", "最大奖金金额不能小于最小奖金金额");
            }
            tier.setBonusMaxAmount(maxBonus);
            tier.setSortOrder(request.sortOrder() == null ? index + 1 : request.sortOrder());
            tiers.add(tier);
        }
        tierRepository.saveAll(tiers);
    }

    private RedemptionDtos.CampaignResponse campaignResponse(RedemptionCampaign campaign) {
        List<RedemptionDtos.TierResponse> tiers = tierRepository.findByCampaignIdOrderBySortOrderAscMinDepositAmountAsc(campaign.getId())
                .stream().map(this::tierResponse).toList();
        return new RedemptionDtos.CampaignResponse(campaign.getId(), campaign.getCode(), campaign.getName(), campaign.getStatus(),
                campaign.getLookbackDays(), campaign.getDescription(), tiers,
                issueRepository.countImportedCodesByCampaignId(campaign.getId()),
                issueRepository.countByCampaignIdAndState(campaign.getId(), "FAILED"), campaign.getRowVersion(),
                campaign.getCreatedAt(), campaign.getUpdatedAt());
    }

    private RedemptionDtos.TierResponse tierResponse(RedemptionCampaignTier tier) {
        return new RedemptionDtos.TierResponse(tier.getId(), tier.getDisplayName(), tier.getMinDepositAmount(), tier.getBonusAmount(),
                tier.getBonusMaxAmount(), tier.getSortOrder(), tier.getRowVersion());
    }

    private RedemptionDtos.CodeIssueResponse issueResponse(RedemptionCodeIssue issue) {
        return new RedemptionDtos.CodeIssueResponse(issue.getId(), issue.getCampaignId(), issue.getCampaignTierId(), issue.getTierName(),
                issue.getMinDepositAmount(), issue.getBonusAmount(), issue.getClaimDate(), issue.getDepositWindowStart(),
                issue.getDepositWindowEnd(), issue.getCodes().isEmpty() ? null : String.join("\n", issue.getCodes()), issue.getState(), issue.getRemoteReferenceId(),
                issue.getRemoteError(), issue.getGeneratedAt(), issue.getRowVersion(), issue.getBonusMaxAmount(), issue.getBatchId(),
                issue.getWorkflowStatus(), issue.getRemoteConfigurationId(), issue.getRemoteGroupKey(), parseLabelIds(issue.getRemoteLabelIdsJson()));
    }

    private Map<String, Object> auditCampaignSummary(RedemptionDtos.CampaignResponse response) {
        return Map.of("code", response.code(), "name", response.name(), "status", response.status(), "lookbackDays", response.lookbackDays(),
                "tierCount", response.tiers().size());
    }

    private RedemptionCampaign requireCampaign(Long id) {
        return campaignRepository.findById(id).orElseThrow(() -> ApiException.notFound("充值领码活动"));
    }

    private RedemptionCodeBatch requireBatch(Long id) {
        return batchRepository.findById(id).orElseThrow(() -> ApiException.notFound("兑换码批次"));
    }

    private RedemptionCodeIssue requireIssue(Long id) {
        return issueRepository.findById(id).orElseThrow(() -> ApiException.notFound("兑换码任务"));
    }

    private RedemptionCodeBatch requireManualBatch(RedemptionCodeIssue issue) {
        if (issue.getBatchId() == null) throw ApiException.conflict("NOT_MANUAL_BATCH_TASK", "该兑换码任务不属于人工操作批次");
        return requireBatch(issue.getBatchId());
    }

    private RedemptionCodeBatch refreshBatchStatus(RedemptionCodeBatch batch) {
        int expected = batch.getExpectedCodeCount();
        int imported = Math.toIntExact(issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "CODE_IMPORTED"));
        int pending = Math.toIntExact(issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "PENDING_CREATION"));
        if (imported == expected) batch.setStatus("COMPLETED");
        else if (batch.getPublishedAt() != null) batch.setStatus("PUBLISHED");
        else if (pending == 0 && issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "CREATED") == expected) {
            batch.setStatus("READY_TO_PUBLISH");
        } else batch.setStatus("CREATING");
        return batchRepository.save(batch);
    }

    private RedemptionDtos.BatchDetailResponse batchDetail(RedemptionCodeBatch batch) {
        return new RedemptionDtos.BatchDetailResponse(batchResponse(batch),
                issueRepository.findByBatchIdOrderByClaimDateAscCampaignTierIdAsc(batch.getId()).stream().map(this::issueResponse).toList());
    }

    @Transactional(readOnly = true)
    public List<RedemptionDtos.BatchDetailResponse> exportGroup(String exportGroupKey) {
        if (exportGroupKey == null || exportGroupKey.isBlank()) throw ApiException.badRequest("EXPORT_GROUP_REQUIRED", "请提供导出组标识");
        List<RedemptionCodeBatch> batches = batchRepository.findByExportGroupKeyOrderByCreatedAtAsc(exportGroupKey.trim());
        if (batches.isEmpty()) throw ApiException.notFound("兑换码多盘口导出组");
        return batches.stream().map(this::batchDetail).toList();
    }

    private RedemptionDtos.BatchResponse batchResponse(RedemptionCodeBatch batch) {
        RedemptionRemoteDirectory.Account connection = batch.getRemoteConnectionId() == null ? null
                : remoteDirectory.find(batch.getRemoteConnectionId()).orElse(null);
        String connectionName = batch.getRemoteConnectionId() == null ? null
                : connection == null ? "已删除的远端连接" : connection.username();
        String marketCode = connection == null ? null : connection.marketCode();
        String marketName = connection == null ? null : connection.marketName();
        return new RedemptionDtos.BatchResponse(batch.getId(), batch.getCampaignId(), batch.getClaimDateFrom(), batch.getClaimDateTo(),
                batch.getValidFromDayOffset(), batch.getValidToDayOffset(),
                batch.getLookbackDays(), batch.getRedemptionType(), batch.getExpectedCodeCount(), batch.getStatus(),
                Math.toIntExact(issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "PENDING_CREATION")),
                Math.toIntExact(issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "CREATED")),
                Math.toIntExact(issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "PUBLISHED")),
                Math.toIntExact(issueRepository.countByBatchIdAndWorkflowStatus(batch.getId(), "CODE_IMPORTED")),
                batch.getPublishedAt(), batch.getRowVersion(), batch.getCreatedAt(), batch.getRemoteConnectionId(), connectionName, marketCode, marketName,
                batch.getExportGroupKey(),
                batch.getRemotePublishTaskId(), batch.getRemotePublishError(), batch.getRemotePublishMode(),
                batch.getRemoteScheduledPublishAt(), batch.getRemotePublishNote(), batch.getRemotePublishCancelledAt(), remoteOptionsResponse(batch),
                batch.getTaskId());
    }

    private RedemptionCodeTask resolveTask(String exportGroupKey) {
        if (exportGroupKey == null || exportGroupKey.isBlank()) return createStandaloneTask();
        String groupingKey = "group:" + exportGroupKey.trim();
        return taskRepository.findByGroupingKey(groupingKey).orElseGet(() -> createTask(groupingKey));
    }

    private RedemptionCodeTask createStandaloneTask() {
        return createTask("request:" + UUID.randomUUID());
    }

    private RedemptionCodeTask createTask(String groupingKey) {
        RedemptionCodeTask task = new RedemptionCodeTask();
        task.setGroupingKey(groupingKey);
        task.setCreatedBy(currentUser.require().id());
        return taskRepository.save(task);
    }

    private void applyRemoteOptions(RedemptionCodeBatch batch, RedemptionDtos.RemoteCreationOptionsRequest request) {
        if (request == null) throw ApiException.badRequest("REMOTE_BATCH_OPTIONS_REQUIRED", "请填写本批次的远端创建参数");
        batch.setRemotePublishEnvironment(request.publishEnvironment());
        batch.setRemoteFlowTimes(request.flowTimes());
        batch.setRemoteCreationIntervalSeconds(request.creationIntervalSeconds());
        batch.setRemoteActivityRecharge(request.activityRecharge());
        batch.setRemoteActivityRechargeCount(request.activityRechargeCount());
        batch.setRemoteActivityId(request.activityId());
        batch.setRemoteKeyNumber(request.keyNumber());
        batch.setRemoteSingleUserLimit(request.singleUserLimit());
        batch.setRemoteSingleKeyLimit(request.singleKeyLimit());
        batch.setRemoteRequireBindBankCard(request.requireBindBankCard());
        batch.setRemoteRequireBindPhone(request.requireBindPhone());
        batch.setRemoteCheckUuid(request.checkUuid());
        batch.setRemoteUuidRewardLimit(request.uuidRewardLimit());
        batch.setRemoteCheckLoginIp(request.checkLoginIp());
        batch.setRemoteLoginIpRewardLimit(request.loginIpRewardLimit());
        batch.setRemoteCheckRegisterIp(request.checkRegisterIp());
        batch.setRemoteRegisterIpRewardLimit(request.registerIpRewardLimit());
    }

    private RedemptionDtos.RemoteCreationOptionsResponse remoteOptionsResponse(RedemptionCodeBatch batch) {
        if (batch.getRemoteConnectionId() == null && batch.getRemoteKeyNumber() == null) return null;
        return new RedemptionDtos.RemoteCreationOptionsResponse(batch.getRemotePublishEnvironment(), batch.getRemoteFlowTimes(), batch.getRemoteCreationIntervalSeconds(),
                batch.getRemoteActivityRecharge(), batch.getRemoteActivityRechargeCount(), batch.getRemoteActivityId(),
                batch.getRemoteKeyNumber(), batch.getRemoteSingleUserLimit(), batch.getRemoteSingleKeyLimit(),
                batch.getRemoteRequireBindBankCard(), batch.getRemoteRequireBindPhone(), batch.getRemoteCheckUuid(),
                batch.getRemoteUuidRewardLimit(), batch.getRemoteCheckLoginIp(), batch.getRemoteLoginIpRewardLimit(),
                batch.getRemoteCheckRegisterIp(), batch.getRemoteRegisterIpRewardLimit());
    }

    private void requireRange(LocalDate from, LocalDate to, int maximumDays, String action) {
        if (from == null || to == null || to.isBefore(from)) throw ApiException.badRequest("INVALID_CLAIM_DATE_RANGE", "请选择有效的领取日期范围");
        if (ChronoUnit.DAYS.between(from, to) + 1 > maximumDays) {
            throw ApiException.badRequest("CLAIM_DATE_RANGE_TOO_LARGE", action + "兑换码时最多选择 " + maximumDays + " 天");
        }
    }

    private void requireValidityOffsets(int fromOffset, int toOffset) {
        if (fromOffset < 0 || toOffset < fromOffset || toOffset > 365) {
            throw ApiException.badRequest("INVALID_VALID_TIME_RULE", "兑换码生效结束日不能早于生效开始日，且最多可延后 365 天");
        }
    }

    private String normalizeCode(String code) {
        String normalized = requiredText(code, "活动编码").toUpperCase(Locale.ROOT);
        if (!normalized.matches("[A-Z0-9][A-Z0-9_-]{1,79}")) {
            throw ApiException.badRequest("INVALID_CAMPAIGN_CODE", "活动编码仅支持大写字母、数字、下划线和连字符，长度为 2 到 80");
        }
        return normalized;
    }

    private String normalizeStatus(String status) {
        String normalized = requiredText(status, "活动状态").toUpperCase(Locale.ROOT);
        if (!CAMPAIGN_STATUSES.contains(normalized)) throw ApiException.badRequest("INVALID_CAMPAIGN_STATUS", "活动状态不合法");
        return normalized;
    }
    private BigDecimal normalizedAmount(BigDecimal value, String field) {
        DecimalUtils.requireNonNegative(field, value);
        return DecimalUtils.amount(value);
    }
    private void verifyVersion(Long actual, Long requested) {
        verifyVersion(actual, requested, "CAMPAIGN_VERSION_CONFLICT", "活动已被其他人修改，请刷新后重试");
    }
    private void verifyVersion(Long actual, Long requested, String code, String message) {
        if (requested == null || !Objects.equals(actual, requested)) throw ApiException.conflict(code, message);
    }
    private String requiredText(String value, String field) {
        String normalized = trimToNull(value);
        if (normalized == null) throw ApiException.badRequest("FIELD_REQUIRED", field + "不能为空");
        return normalized;
    }
    private String trimToNull(String value) { return value == null || value.isBlank() ? null : value.trim(); }
    private List<List<Long>> normalizeTierLabelIds(RedemptionDtos.CodeGroupCreateRequest request, RedemptionCodeType redemptionType) {
        List<List<Long>> labels = request.tierLabelIds();
        if (labels.size() != request.tiers().size()) {
            throw ApiException.badRequest("INVALID_TIER_AUDIENCES", "每个充值档位都必须提供一个用户类型");
        }
        List<String> userTypes = request.tierUserTypes();
        boolean explicitUserTypes = userTypes != null && !userTypes.isEmpty();
        if (explicitUserTypes && userTypes.size() != request.tiers().size()) {
            throw ApiException.badRequest("INVALID_TIER_AUDIENCES", "每个充值档位都必须提供一个用户类型");
        }
        List<List<Long>> normalized = new ArrayList<>();
        for (int index = 0; index < request.tiers().size(); index++) {
            List<Long> tierLabels = labels.get(index) == null ? List.of() : labels.get(index);
            String userType = explicitUserTypes ? userTypes.get(index) : legacyUserType(redemptionType, request.tiers().get(index), tierLabels);
            if ("ALL_USERS".equals(userType)) {
                if (!tierLabels.isEmpty()) {
                    throw ApiException.badRequest("ALL_USERS_LABELS_NOT_ALLOWED", "全部用户档位不能同时配置标签 ID");
                }
                normalized.add(List.of());
                continue;
            }
            if (!"LABEL_USERS".equals(userType) || tierLabels.isEmpty() || tierLabels.stream().anyMatch(id -> id == null || id <= 0)) {
                throw ApiException.badRequest("REMOTE_TIER_LABEL_REQUIRED", "标签用户档位必须选择至少一个远端用户标签");
            }
            normalized.add(List.copyOf(tierLabels));
        }
        return normalized;
    }

    private String legacyUserType(RedemptionCodeType redemptionType, RedemptionDtos.TierRequest tier, List<Long> labels) {
        if (redemptionType == RedemptionCodeType.PREVIOUS_DAY_DEPOSIT
                && tier.minDepositAmount().signum() == 0 && labels.isEmpty()) return "ALL_USERS";
        return "LABEL_USERS";
    }

    private void validateLabelIds(RedemptionCodeType redemptionType, RedemptionCampaignTier tier, List<Long> labelIds) {
        if (labelIds != null && labelIds.stream().anyMatch(id -> id == null || id <= 0)) {
            throw ApiException.badRequest("REMOTE_TIER_LABEL_INVALID", "远端用户标签 ID 必须为正整数" + (tier.getDisplayName() == null ? "" : "：" + tier.getDisplayName()));
        }
    }
    private String serializeLabelIds(List<Long> labelIds) {
        try { return objectMapper.writeValueAsString(labelIds == null ? List.of() : labelIds); }
        catch (JsonProcessingException exception) { throw new IllegalStateException("无法保存远端用户标签", exception); }
    }
    private List<Long> parseLabelIds(String value) {
        if (value == null || value.isBlank()) return List.of();
        try { return objectMapper.readValue(value, new TypeReference<List<Long>>() { }); }
        catch (JsonProcessingException exception) { return List.of(); }
    }
}
