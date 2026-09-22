package com.rajads.erp.redemption;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;

public interface RedemptionCampaignTierRepository extends JpaRepository<RedemptionCampaignTier, Long> {
    List<RedemptionCampaignTier> findByCampaignIdOrderBySortOrderAscMinDepositAmountAsc(Long campaignId);
    long countByCampaignId(Long campaignId);
    void deleteByCampaignId(Long campaignId);
    List<RedemptionCampaignTier> findByCampaignIdIn(Collection<Long> campaignIds);
}
