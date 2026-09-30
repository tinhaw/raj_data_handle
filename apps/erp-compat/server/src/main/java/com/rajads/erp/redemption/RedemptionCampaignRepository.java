package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface RedemptionCampaignRepository extends JpaRepository<RedemptionCampaign, Long> {
    List<RedemptionCampaign> findAllByOrderByCreatedAtDesc();
    Optional<RedemptionCampaign> findByCodeIgnoreCase(String code);
}
