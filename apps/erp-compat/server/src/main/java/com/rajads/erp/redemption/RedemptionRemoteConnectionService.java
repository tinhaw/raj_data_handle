package com.rajads.erp.redemption;

import com.rajads.erp.audit.AuditService;
import com.rajads.erp.config.RemoteOperationGate;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.identity.CurrentUser;
import com.rajads.erp.shared.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.net.URI;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Collection;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;

/** Manages reusable market endpoints and their remote accounts without returning credentials to the browser. */
@Service
@RequiredArgsConstructor
public class RedemptionRemoteConnectionService {
    private final RedemptionRemoteConnectionRepository repository;
    private final RedemptionRemoteMarketRepository marketRepository;
    private final RedemptionCodeBatchRepository batchRepository;
    private final RedemptionRewardTierPresetRepository rewardTierPresetRepository;
    private final RemoteOperationGate remoteOperationGate;
    private final RemoteConnectionCredentialCipher credentialCipher;
    private final RemoteGiftCodeBackendClient remoteClient;
    private final ObjectMapper objectMapper;
    private final CurrentUser currentUser;
    private final AuditService auditService;

    @Transactional(readOnly = true)
    public List<RedemptionDtos.RemoteMarketResponse> listMarkets() {
        return marketRepository.findAllByOrderByEnabledDescNameAsc().stream().map(this::marketResponse).toList();
    }

    @Transactional
    public RedemptionDtos.RemoteMarketResponse createMarket(RedemptionDtos.RemoteMarketCreateRequest request) {
        String code = normalizeMarketCode(request.code());
        if (marketRepository.findByCodeIgnoreCase(code).isPresent()) throw ApiException.conflict("REMOTE_MARKET_CODE_EXISTS", "盘口编码已存在");
        String baseUrl = normalizeBaseUrl(request.baseUrl());
        if (marketRepository.findByBaseUrlIgnoreCase(baseUrl).isPresent()) throw ApiException.conflict("REMOTE_MARKET_BASE_URL_EXISTS", "该远端 Base URL 已配置为盘口");
        RedemptionRemoteMarket market = new RedemptionRemoteMarket();
        market.setCode(code);
        market.setName(requiredText(request.name(), "盘口名称"));
        market.setBaseUrl(baseUrl);
        market.setEnabled(request.enabled() == null || request.enabled());
        market.setCreatedBy(currentUser.require().id());
        market.setUpdatedBy(currentUser.require().id());
        market = marketRepository.save(market);
        auditService.record("REDEMPTION_REMOTE_MARKET_CREATED", "REDEMPTION_REMOTE_MARKET", market.getId().toString(), null, null,
                Map.of("code", market.getCode(), "name", market.getName(), "baseUrl", market.getBaseUrl()));
        return marketResponse(market);
    }

    @Transactional
    public RedemptionDtos.RemoteMarketResponse patchMarket(Long id, RedemptionDtos.RemoteMarketPatchRequest request) {
        RedemptionRemoteMarket market = requireMarket(id);
        verifyVersion(market.getRowVersion(), request.rowVersion(), "REMOTE_MARKET_VERSION_CONFLICT", "盘口已被其他人修改，请刷新后重试");
        if (request.name() != null) market.setName(requiredText(request.name(), "盘口名称"));
        if (request.baseUrl() != null) {
            String baseUrl = normalizeBaseUrl(request.baseUrl());
            marketRepository.findByBaseUrlIgnoreCase(baseUrl).filter(other -> !other.getId().equals(id))
                    .ifPresent(other -> { throw ApiException.conflict("REMOTE_MARKET_BASE_URL_EXISTS", "该远端 Base URL 已配置为盘口"); });
            if (!baseUrl.equals(market.getBaseUrl())) {
                market.setBaseUrl(baseUrl);
                List<RedemptionRemoteConnection> accounts = repository.findAllByMarketId(id);
                accounts.forEach(account -> {
                    account.setBaseUrl(baseUrl);
                    clearSession(account);
                });
                repository.saveAll(accounts);
            }
        }
        if (request.enabled() != null) market.setEnabled(request.enabled());
        market.setUpdatedBy(currentUser.require().id());
        market = marketRepository.save(market);
        auditService.record("REDEMPTION_REMOTE_MARKET_UPDATED", "REDEMPTION_REMOTE_MARKET", id.toString(), null, null,
                Map.of("code", market.getCode(), "name", market.getName(), "enabled", market.isEnabled()));
        return marketResponse(market);
    }

    @Transactional(readOnly = true)
    public List<RedemptionDtos.RemoteConnectionResponse> list() {
        List<RedemptionRemoteConnection> connections = repository.findAllByOrderByEnabledDescUsernameAsc();
        Map<Long, RedemptionRemoteMarket> markets = marketRepository.findAllById(connections.stream()
                        .map(RedemptionRemoteConnection::getMarketId).filter(java.util.Objects::nonNull).toList())
                .stream().collect(Collectors.toMap(RedemptionRemoteMarket::getId, Function.identity()));
        return connections.stream().map(item -> response(item, markets.get(item.getMarketId()))).toList();
    }

    @Transactional
    public RedemptionDtos.RemoteConnectionResponse create(RedemptionDtos.RemoteConnectionCreateRequest request) {
        String username = normalizeUsername(request.username());
        RedemptionRemoteMarket market = requireEnabledMarket(request.marketId());
        requireAvailableUsername(market.getId(), username, null);
        RedemptionRemoteConnection connection = new RedemptionRemoteConnection();
        connection.setCode(nextInternalCode());
        connection.setName(username);
        connection.setUsername(username);
        connection.setMarketId(market.getId());
        connection.setBaseUrl(market.getBaseUrl());
        connection.setPasswordCiphertext(credentialCipher.encrypt(requiredText(request.password(), "登录密码")));
        connection.setTotpSecretCiphertext(credentialCipher.encrypt(requiredText(request.totpSecret(), "TOTP 秘钥")));
        connection.setEnabled(request.enabled() == null || request.enabled());
        connection.setCreatedBy(currentUser.require().id());
        connection.setUpdatedBy(currentUser.require().id());
        connection = repository.save(connection);
        auditService.record("REDEMPTION_REMOTE_CONNECTION_CREATED", "REDEMPTION_REMOTE_CONNECTION", connection.getId().toString(), null, null,
                Map.of("username", connection.getUsername(), "marketCode", market.getCode()));
        return response(connection, market);
    }

    @Transactional
    public RedemptionDtos.RemoteConnectionResponse patch(Long id, RedemptionDtos.RemoteConnectionPatchRequest request) {
        RedemptionRemoteConnection connection = require(id);
        verifyVersion(connection.getRowVersion(), request.rowVersion(), "REMOTE_CONNECTION_VERSION_CONFLICT", "远端账号已被其他人修改，请刷新后重试");
        RedemptionRemoteMarket market = request.marketId() != null && !request.marketId().equals(connection.getMarketId())
                ? requireEnabledMarket(request.marketId()) : requireMarket(connection.getMarketId());
        String username = request.username() == null ? connection.getUsername() : normalizeUsername(request.username());
        requireAvailableUsername(market.getId(), username, id);
        boolean reloginRequired = false;
        if (!username.equals(connection.getUsername())) {
            connection.setUsername(username);
            connection.setName(username);
            reloginRequired = true;
        }
        if (!market.getId().equals(connection.getMarketId())) {
            connection.setMarketId(market.getId());
            connection.setBaseUrl(market.getBaseUrl());
            reloginRequired = true;
        }
        if (request.password() != null && !request.password().isBlank()) {
            connection.setPasswordCiphertext(credentialCipher.encrypt(requiredText(request.password(), "登录密码")));
            reloginRequired = true;
        }
        if (request.totpSecret() != null && !request.totpSecret().isBlank()) {
            connection.setTotpSecretCiphertext(credentialCipher.encrypt(requiredText(request.totpSecret(), "TOTP 秘钥")));
            reloginRequired = true;
        }
        if (request.enabled() != null) connection.setEnabled(request.enabled());
        if (reloginRequired) clearSession(connection);
        connection.setUpdatedBy(currentUser.require().id());
        connection = repository.save(connection);
        auditService.record("REDEMPTION_REMOTE_CONNECTION_UPDATED", "REDEMPTION_REMOTE_CONNECTION", id.toString(), null, null,
                Map.of("username", connection.getUsername(), "marketCode", market.getCode(), "enabled", connection.isEnabled()));
        return response(connection, market);
    }

    /**
     * An account that has generated a batch stays in place so the batch retains
     * its remote-account traceability. Operators can still disable that account.
     */
    @Transactional
    public void delete(Long id, RedemptionDtos.RemoteConnectionDeleteRequest request) {
        RedemptionRemoteConnection connection = require(id);
        verifyVersion(connection.getRowVersion(), request.rowVersion(), "REMOTE_CONNECTION_VERSION_CONFLICT", "远端账号已被其他人修改，请刷新后重试");
        long batchCount = batchRepository.countByRemoteConnectionId(id);
        if (batchCount > 0) {
            throw ApiException.conflict("REMOTE_CONNECTION_HAS_BATCHES",
                    "该远端账号已用于 " + batchCount + " 个兑换码批次，不能删除；请停用账号以保留历史批次记录",
                    Map.of("batchCount", batchCount));
        }
        String username = connection.getUsername();
        repository.delete(connection);
        repository.flush();
        auditService.record("REDEMPTION_REMOTE_CONNECTION_DELETED", "REDEMPTION_REMOTE_CONNECTION", id.toString(), null, null,
                Map.of("username", username));
    }

    @Transactional(noRollbackFor = ApiException.class)
    public RedemptionDtos.RemoteConnectionCheckResponse check(Long id) {
        remoteOperationGate.requireEnabled("connection_check");
        RedemptionRemoteConnection connection = requireEnabled(id);
        try {
            String message = remoteClient.check(connection);
            recordCheckResult(connection, null);
            return new RedemptionDtos.RemoteConnectionCheckResponse(true, message, Instant.now());
        } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
            recordCheckResult(connection, limit(exception.getMessage()));
            throw ApiException.badRequest("REMOTE_CONNECTION_CHECK_FAILED", limit(exception.getMessage()));
        }
    }

    public List<RedemptionDtos.RemoteTagResponse> tags(Long id) {
        remoteOperationGate.requireEnabled("tag_read");
        RedemptionRemoteConnection connection = requireEnabled(id);
        try {
            return remoteClient.tags(connection).stream().map(tag -> new RedemptionDtos.RemoteTagResponse(tag.id(), tag.name())).toList();
        } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
            updateCheckResult(connection.getId(), limit(exception.getMessage()));
            throw ApiException.badRequest("REMOTE_TAGS_LOAD_FAILED", limit(exception.getMessage()));
        }
    }

    /**
     * Tag IDs are scoped to a remote market. Check the account selected for the
     * batch immediately before creation so mappings copied from another market
     * cannot silently target the wrong audience.
     */
    public void requireCurrentTags(Long id, Collection<Long> requestedTagIds) {
        if (requestedTagIds == null || requestedTagIds.isEmpty()) return;
        HashSet<Long> expected = new HashSet<>(requestedTagIds);
        HashSet<Long> available = tags(id).stream().map(RedemptionDtos.RemoteTagResponse::id)
                .collect(Collectors.toCollection(HashSet::new));
        List<Long> missing = expected.stream().filter(tagId -> !available.contains(tagId)).sorted().toList();
        if (!missing.isEmpty()) {
            throw ApiException.conflict("REMOTE_TAG_NOT_AVAILABLE",
                    "所选盘口不存在标签 ID：" + missing + "；请先同步标签并按当前盘口重新配置兑换码档位");
        }
    }

    /**
     * A sync is always intentional. It refreshes only after an operator asks for it and makes any existing
     * reward mapping require confirmation and re-saving against the just-fetched tag directory.
     */
    @Transactional(noRollbackFor = ApiException.class)
    public RedemptionDtos.RemoteTagSyncResponse syncTags(Long id) {
        remoteOperationGate.requireEnabled("tag_sync");
        RedemptionRemoteConnection connection = requireEnabled(id);
        try {
            List<RedemptionDtos.RemoteTagResponse> tags = remoteClient.tags(connection).stream()
                    .map(tag -> new RedemptionDtos.RemoteTagResponse(tag.id(), tag.name())).toList();
            Instant syncedAt = Instant.now();
            boolean presetStale = rewardTierPresetRepository.findById(id).map(preset -> {
                preset.setStale(true);
                preset.setLastSyncedAt(syncedAt);
                rewardTierPresetRepository.save(preset);
                return true;
            }).orElse(false);
            auditService.record("REDEMPTION_REMOTE_TAGS_SYNCED", "REDEMPTION_REMOTE_CONNECTION", id.toString(), null, null,
                    Map.of("tagCount", tags.size(), "presetMarkedStale", presetStale));
            return new RedemptionDtos.RemoteTagSyncResponse(tags, presetStale, syncedAt);
        } catch (RemoteGiftCodeBackendClient.RemoteGiftCodeException exception) {
            updateCheckResult(connection.getId(), limit(exception.getMessage()));
            throw ApiException.badRequest("REMOTE_TAGS_LOAD_FAILED", limit(exception.getMessage()));
        }
    }

    @Transactional(readOnly = true)
    public RedemptionDtos.RewardTierPresetResponse rewardTierPreset(Long id) {
        requireEnabled(id);
        return rewardTierPresetRepository.findById(id).map(this::presetResponse)
                .orElseGet(() -> new RedemptionDtos.RewardTierPresetResponse(false, false, List.of(), List.of(), null, null));
    }

    @Transactional
    public RedemptionDtos.RewardTierPresetResponse saveRewardTierPreset(Long id, RedemptionDtos.RewardTierPresetSaveRequest request) {
        requireEnabled(id);
        validatePreset(request);
        RedemptionRewardTierPreset preset = rewardTierPresetRepository.findById(id).orElseGet(RedemptionRewardTierPreset::new);
        preset.setRemoteConnectionId(id);
        preset.setTiersJson(writeJson(request.tiers(), "奖励分档预设"));
        preset.setTagSnapshotJson(writeJson(request.tagSnapshot(), "标签 ID 数组快照"));
        preset.setStale(false);
        preset.setSavedAt(Instant.now());
        preset.setSavedBy(currentUser.require().id());
        preset = rewardTierPresetRepository.save(preset);
        auditService.record("REDEMPTION_REWARD_TIER_PRESET_SAVED", "REDEMPTION_REMOTE_CONNECTION", id.toString(), null, null,
                Map.of("tierCount", request.tiers().size(), "tagCount", request.tagSnapshot().size()));
        return presetResponse(preset);
    }

    @Transactional(readOnly = true)
    public RedemptionRemoteConnection requireEnabled(Long id) {
        RedemptionRemoteConnection connection = require(id);
        if (!connection.isEnabled()) throw ApiException.conflict("REMOTE_CONNECTION_DISABLED", "所选远端账号已停用，请选择其他可用账号");
        if (!requireMarket(connection.getMarketId()).isEnabled()) throw ApiException.conflict("REMOTE_MARKET_DISABLED", "所选盘口已停用，请选择其他可用盘口账号");
        return connection;
    }

    /**
     * Code-group creation is market-driven.  Pick the first enabled account in
     * a stable username order so the browser never has to expose an account
     * picker and retries resolve to the same account while its configuration is unchanged.
     */
    @Transactional(readOnly = true)
    public RedemptionRemoteConnection selectEnabledForMarket(Long marketId) {
        RedemptionRemoteMarket market = requireEnabledMarket(marketId);
        return repository.findFirstByMarketIdAndEnabledTrueOrderByUsernameAsc(market.getId())
                .orElseThrow(() -> ApiException.conflict("REMOTE_MARKET_NO_AVAILABLE_CONNECTION",
                        "所选盘口暂无可用远端账号，请前往“远端连接”配置或启用账号"));
    }

    @Transactional(readOnly = true)
    public RedemptionRemoteConnection require(Long id) { return repository.findById(id).orElseThrow(() -> ApiException.notFound("远端账号")); }

    @Transactional
    void updateCheckResult(Long id, String error) {
        repository.findById(id).ifPresent(connection -> {
            recordCheckResult(connection, error);
            repository.save(connection);
        });
    }

    private void recordCheckResult(RedemptionRemoteConnection connection, String error) {
        connection.setLastCheckedAt(Instant.now());
        connection.setLastError(error);
    }
    private void validatePreset(RedemptionDtos.RewardTierPresetSaveRequest request) {
        HashSet<Long> labels = new HashSet<>();
        request.tiers().forEach(tier -> {
            if (tier.bonusMaxAmount().compareTo(tier.bonusAmount()) < 0) {
                throw ApiException.badRequest("INVALID_REWARD_TIER_PRESET", "奖励金额上限不能小于下限");
            }
            tier.labelIds().forEach(labelId -> {
                if (!labels.add(labelId)) throw ApiException.badRequest("DUPLICATE_REWARD_TIER_LABEL", "同一个标签 ID 不能重复保存到多个奖励分档");
            });
        });
        HashSet<Long> snapshotIds = new HashSet<>();
        request.tagSnapshot().forEach(tag -> snapshotIds.add(tag.id()));
        if (!snapshotIds.containsAll(labels)) throw ApiException.badRequest("REWARD_TIER_LABEL_SNAPSHOT_MISSING", "奖励分档中的标签 ID 必须存在于当前标签快照");
    }
    private RedemptionDtos.RewardTierPresetResponse presetResponse(RedemptionRewardTierPreset preset) {
        return new RedemptionDtos.RewardTierPresetResponse(true, preset.isStale(),
                readPresetTiers(preset.getTiersJson()), readTagSnapshot(preset.getTagSnapshotJson()), preset.getSavedAt(), preset.getLastSyncedAt());
    }
    private List<RedemptionDtos.RewardTierPresetTierResponse> readPresetTiers(String value) {
        try {
            return objectMapper.readValue(value, new TypeReference<List<RedemptionDtos.RewardTierPresetTierResponse>>() { });
        } catch (JsonProcessingException exception) {
            throw ApiException.conflict("REWARD_TIER_PRESET_INVALID", "已保存的奖励分档预设无法读取，请重新保存");
        }
    }
    private List<RedemptionDtos.RemoteTagResponse> readTagSnapshot(String value) {
        try {
            return objectMapper.readValue(value, new TypeReference<List<RedemptionDtos.RemoteTagResponse>>() { });
        } catch (JsonProcessingException exception) {
            throw ApiException.conflict("REWARD_TIER_PRESET_INVALID", "已保存的标签 ID 快照无法读取，请重新保存");
        }
    }
    private String writeJson(Object value, String label) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw ApiException.badRequest("REWARD_TIER_PRESET_INVALID", label + "无法保存");
        }
    }

    private RedemptionRemoteMarket requireMarket(Long id) {
        if (id == null) throw ApiException.conflict("REMOTE_MARKET_REQUIRED", "远端账号必须选择盘口");
        return marketRepository.findById(id).orElseThrow(() -> ApiException.notFound("远端盘口"));
    }
    private RedemptionRemoteMarket requireEnabledMarket(Long id) {
        RedemptionRemoteMarket market = requireMarket(id);
        if (!market.isEnabled()) throw ApiException.conflict("REMOTE_MARKET_DISABLED", "所选盘口已停用，请选择已启用盘口");
        return market;
    }
    private RedemptionDtos.RemoteMarketResponse marketResponse(RedemptionRemoteMarket item) {
        return new RedemptionDtos.RemoteMarketResponse(item.getId(), item.getCode(), item.getName(), item.getBaseUrl(), item.isEnabled(),
                item.getRowVersion(), item.getCreatedAt(), item.getUpdatedAt());
    }
    private RedemptionDtos.RemoteConnectionResponse response(RedemptionRemoteConnection item, RedemptionRemoteMarket market) {
        boolean activeSession = item.getAccessTokenCiphertext() != null && !item.getAccessTokenCiphertext().isBlank()
                && (item.getAccessTokenExpiresAt() == null || item.getAccessTokenExpiresAt().isAfter(Instant.now().plusSeconds(60)));
        return new RedemptionDtos.RemoteConnectionResponse(item.getId(), item.getUsername(), item.getMarketId(),
                market == null ? "" : market.getCode(), market == null ? "已删除盘口" : market.getName(), market != null && market.isEnabled(),
                item.getBaseUrl(), item.getPasswordCiphertext() != null && !item.getPasswordCiphertext().isBlank(),
                item.getTotpSecretCiphertext() != null && !item.getTotpSecretCiphertext().isBlank(), activeSession,
                item.getAccessTokenExpiresAt(), item.getLastLoggedInAt(), item.isEnabled(), item.getLastCheckedAt(), item.getLastError(),
                item.getRowVersion(), item.getCreatedAt(), item.getUpdatedAt());
    }
    private String normalizeMarketCode(String value) {
        String code = requiredText(value, "盘口编码").toUpperCase(Locale.ROOT);
        if (!code.matches("[A-Z0-9][A-Z0-9_-]{1,59}")) throw ApiException.badRequest("INVALID_REMOTE_MARKET_CODE", "盘口编码仅支持大写字母、数字、下划线和连字符，长度为 2 到 60");
        return code;
    }
    private void requireAvailableUsername(Long marketId, String username, Long currentId) {
        repository.findByMarketIdAndUsernameIgnoreCase(marketId, username)
                .filter(other -> !other.getId().equals(currentId))
                .ifPresent(other -> { throw ApiException.conflict("REMOTE_CONNECTION_USERNAME_EXISTS", "该盘口下的远端账号名已存在"); });
    }
    private String normalizeUsername(String value) { return requiredText(value, "远端账号名"); }
    private String nextInternalCode() { return "ACC_" + UUID.randomUUID().toString().replace("-", "").substring(0, 28).toUpperCase(Locale.ROOT); }
    private String normalizeBaseUrl(String value) {
        String url = requiredText(value, "远端 Base URL").replaceAll("/+$", "");
        if (url.endsWith("/api")) url = url.substring(0, url.length() - 4);
        try {
            URI uri = URI.create(url);
            if (!("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme())) || uri.getHost() == null || uri.getQuery() != null || uri.getFragment() != null) throw new IllegalArgumentException();
            return url;
        } catch (IllegalArgumentException exception) {
            throw ApiException.badRequest("INVALID_REMOTE_BASE_URL", "远端 Base URL 必须是完整的 http:// 或 https:// 地址，且不能包含查询参数");
        }
    }
    private void clearSession(RedemptionRemoteConnection connection) {
        connection.setAccessTokenCiphertext(null);
        connection.setAccessTokenExpiresAt(null);
        connection.setLastLoggedInAt(null);
    }
    private void verifyVersion(Long actual, Long requested, String code, String message) {
        if (requested == null || !requested.equals(actual)) throw ApiException.conflict(code, message);
    }
    private String requiredText(String value, String field) { if (value == null || value.isBlank()) throw ApiException.badRequest("FIELD_REQUIRED", field + "不能为空"); return value.trim(); }
    private String limit(String value) { String safe = value == null || value.isBlank() ? "远端管理后台请求失败" : value.trim(); return safe.length() <= 1000 ? safe : safe.substring(0, 1000); }
}
