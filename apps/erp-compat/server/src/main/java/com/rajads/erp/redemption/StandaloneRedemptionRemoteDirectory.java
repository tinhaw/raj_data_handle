package com.rajads.erp.redemption;

import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Collection;
import java.util.Optional;

/** Legacy repository adapter retained only for the standalone regression fixture. */
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "true")
public class StandaloneRedemptionRemoteDirectory implements RedemptionRemoteDirectory {
    private final RedemptionRemoteConnectionService service;
    private final RedemptionRemoteConnectionRepository connectionRepository;
    private final RedemptionRemoteMarketRepository marketRepository;

    @Override
    public Account requireEnabled(Long id) {
        return account(service.requireEnabled(id));
    }

    @Override
    public Account selectEnabledForMarket(Long marketId) {
        return account(service.selectEnabledForMarket(marketId));
    }

    @Override
    public void requireCurrentTags(Long id, Collection<Long> requestedTagIds) {
        service.requireCurrentTags(id, requestedTagIds);
    }

    @Override
    public Optional<Account> find(Long id) {
        return connectionRepository.findById(id).map(this::account);
    }

    private Account account(RedemptionRemoteConnection connection) {
        RedemptionRemoteMarket market = marketRepository.findById(connection.getMarketId()).orElse(null);
        return new Account(
                connection.getId(),
                connection.getUsername(),
                connection.getMarketId(),
                market == null ? "已删除盘口" : market.getCode(),
                market == null ? "已删除盘口" : market.getName(),
                connection.isEnabled(),
                market != null && market.isEnabled()
        );
    }
}
