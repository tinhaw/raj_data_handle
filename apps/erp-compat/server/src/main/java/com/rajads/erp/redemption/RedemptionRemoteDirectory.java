package com.rajads.erp.redemption;

import java.util.Collection;
import java.util.Optional;

/** Secret-free remote-account directory used by local redemption workflows. */
public interface RedemptionRemoteDirectory {
    record Account(
            Long id,
            String username,
            Long marketId,
            String marketCode,
            String marketName,
            boolean enabled,
            boolean marketEnabled
    ) { }

    Account requireEnabled(Long id);

    Account selectEnabledForMarket(Long marketId);

    void requireCurrentTags(Long id, Collection<Long> requestedTagIds);

    Optional<Account> find(Long id);
}
