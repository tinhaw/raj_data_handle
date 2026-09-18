package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface RedemptionRemoteMarketRepository extends JpaRepository<RedemptionRemoteMarket, Long> {
    List<RedemptionRemoteMarket> findAllByOrderByEnabledDescNameAsc();
    Optional<RedemptionRemoteMarket> findByCodeIgnoreCase(String code);
    Optional<RedemptionRemoteMarket> findByBaseUrlIgnoreCase(String baseUrl);
}
