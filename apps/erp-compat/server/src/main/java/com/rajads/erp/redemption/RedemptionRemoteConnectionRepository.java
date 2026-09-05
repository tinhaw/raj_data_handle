package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface RedemptionRemoteConnectionRepository extends JpaRepository<RedemptionRemoteConnection, Long> {
    List<RedemptionRemoteConnection> findAllByOrderByEnabledDescUsernameAsc();
    List<RedemptionRemoteConnection> findAllByMarketId(Long marketId);
    Optional<RedemptionRemoteConnection> findFirstByMarketIdAndEnabledTrueOrderByUsernameAsc(Long marketId);
    Optional<RedemptionRemoteConnection> findByCodeIgnoreCase(String code);
    Optional<RedemptionRemoteConnection> findByMarketIdAndUsernameIgnoreCase(Long marketId, String username);
}
