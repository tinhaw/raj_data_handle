package com.rajads.erp.redemption;

import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;
import org.hibernate.SessionFactory;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/** Protect list reads against per-campaign/per-task queries as history grows. */
@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:redemption_list_queries;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1",
        "spring.jpa.properties.hibernate.generate_statistics=true",
        "logging.level.org.hibernate.engine.internal.StatisticalLoggingSessionEventListener=OFF"
})
@Transactional
class RedemptionListQueryTest {
    @Autowired private EntityManager entityManager;
    @Autowired private EntityManagerFactory entityManagerFactory;
    @Autowired private RedemptionService service;
    @Autowired private com.fasterxml.jackson.databind.ObjectMapper mapper;

    @Test
    void campaignListHasBoundedQueriesAndPreservesCodeCountsAndTierOrder() {
        String prefix = seed(84);
        var statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics();
        statistics.clear();

        var campaigns = service.campaigns().stream().filter(c -> c.code().startsWith(prefix)).toList();

        assertThat(campaigns).hasSize(84);
        assertThat(campaigns).allSatisfy(c -> {
            // Two stored codes plus one legacy scalar code, without double-counting the scalar copy.
            assertThat(c.generatedCodeCount()).isEqualTo(3);
            assertThat(c.failedCodeCount()).isEqualTo(1);
            assertThat(c.tiers()).extracting(RedemptionDtos.TierResponse::displayName)
                    .containsExactly("first", "second", "third");
        });
        assertThat(statistics.getPrepareStatementCount()).isEqualTo(4);
        assertThat(statistics.getCollectionFetchCount()).isZero();
        assertThat(campaigns.getFirst()).isEqualTo(service.campaign(campaigns.getFirst().id()));
    }

    @Test
    void batchOverviewLoadsTaskIdentitiesInBulkWithoutLoadingCodes() {
        String prefix = seed(84);
        var statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics();
        statistics.clear();

        var batches = service.batchOverviews().stream()
                .filter(b -> prefix.equals(b.batch().operatorUsername())).toList();

        assertThat(batches).hasSize(84);
        assertThat(batches).allSatisfy(b -> {
            assertThat(b.batch().taskNumber()).matches("20990101\\d{4}");
            assertThat(b.batch().subtaskNumber()).startsWith(b.batch().taskNumber() + "-");
            assertThat(b.batch().importedCount()).isEqualTo(1);
            assertThat(b.batch().createdCount()).isEqualTo(2);
            assertThat(b.batch().pendingCreationCount()).isZero();
            assertThat(b.batch().publishedCount()).isZero();
            assertThat(b.issues()).hasSize(4).allSatisfy(i -> {
                assertThat(i.redemptionCode()).isNull();
                assertThat(i.redemptionCodes()).isEmpty();
                assertThat(i.remoteGroupKey()).isNull();
                assertThat(i.generatedAt()).isNull();
                assertThat(i.remoteConfigurationName()).isNull();
                assertThat(i.remoteConfigurationRemark()).isNull();
                assertThat(i.remoteReferenceId()).isEqualTo("remote-reference");
                assertThat(i.remoteConfigurationId()).startsWith("remote-configuration-");
                assertThat(i.remoteLabelIds()).containsExactly(123L);
            });
        });
        assertThat(statistics.getPrepareStatementCount()).isEqualTo(3);
        assertThat(statistics.getCollectionFetchCount()).isZero();
        var detail = service.batch(batches.getFirst().batch().id());
        assertThat(detail.issues()).allSatisfy(i -> {
            assertThat(i.remoteGroupKey()).isNotBlank();
            assertThat(i.generatedAt()).isNotNull();
            assertThat(i.remoteConfigurationName()).isNotBlank();
            assertThat(i.remoteConfigurationRemark()).isEqualTo(i.remoteConfigurationName());
        });
    }

    @Test
    void sharedConfigurationsDoNotReintroducePerIssueQueriesOrDuplicateStoredCodes() {
        String prefix = seed(84, true);
        var statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics();
        statistics.clear();
        var batches = service.batchOverviews().stream().filter(b -> prefix.equals(b.batch().operatorUsername())).toList();
        assertThat(batches).hasSize(84).allSatisfy(b -> {
            assertThat(b.batch().importedCount()).isEqualTo(2);
            assertThat(b.issues().get(3).reusedFromIssueId()).isEqualTo(b.issues().getFirst().id());
            assertThat(b.issues().get(3).workflowStatus()).isEqualTo("CODE_IMPORTED");
            assertThat(b.issues().get(3).remoteConfigurationId()).isEqualTo(b.issues().getFirst().remoteConfigurationId());
        });
        assertThat(statistics.getPrepareStatementCount()).isEqualTo(3);
        assertThat(statistics.getCollectionFetchCount()).isZero();
        var detail = service.batch(batches.getFirst().batch().id());
        assertThat(detail.issues().get(3).redemptionCodes()).isEqualTo(detail.issues().getFirst().redemptionCodes());
        var linkedId = detail.issues().get(3).id();
        assertThat(((Number) entityManager.createNativeQuery("select count(*) from erp_compat_redemption_issue_codes where issue_id=:id", Long.class)
                .setParameter("id", linkedId).getSingleResult()).longValue()).isZero();
    }

    @Test
    void campaignWithoutIssuesKeepsZeroCounts() {
        var campaign = new RedemptionCampaign();
        campaign.setCode("empty-" + UUID.randomUUID());
        campaign.setName("Empty list fixture");
        entityManager.persist(campaign);
        entityManager.flush();
        entityManager.clear();

        var listed = service.campaigns().stream().filter(c -> c.id().equals(campaign.getId())).findFirst().orElseThrow();
        assertThat(listed.generatedCodeCount()).isZero();
        assertThat(listed.failedCodeCount()).isZero();
        assertThat(listed.tiers()).isEmpty();
        assertThat(listed).isEqualTo(service.campaign(campaign.getId()));
    }

    @Test
    void compactListPreservesCountsAndHoldsWithoutShippingEveryHistoricalIssue() throws Exception {
        String prefix = seed(1, true);
        var batch = entityManager.createQuery("select b from RedemptionCodeBatch b, RedemptionCodeTask t where b.taskId=t.id and t.createdByUsername=:name", RedemptionCodeBatch.class)
                .setParameter("name", prefix).getSingleResult();
        var template = entityManager.createQuery("select i from RedemptionCodeIssue i where i.batchId=:id order by i.id", RedemptionCodeIssue.class)
                .setParameter("id", batch.getId()).getResultList();
        template.get(1).setRemoteCreateReceiptId("-1");
        template.get(2).setRemoteConfigurationId("-1");
        template.get(2).setRemoteError(RemoteConfigurationIds.AWAITING_REVIEW_PREFIX);
        for (int n=0;n<1000;n++) {
            var issue = new RedemptionCodeIssue();
            issue.setCampaignId(batch.getCampaignId()); issue.setCampaignTierId(template.getFirst().getCampaignTierId());
            issue.setBatchId(batch.getId()); issue.setRemoteMarketId(11L);
            issue.setClaimDate(LocalDate.of(2099,1,1).plusDays(n+4));
            issue.setDepositWindowStart(issue.getClaimDate()); issue.setDepositWindowEnd(issue.getClaimDate());
            issue.setMinDepositAmount(BigDecimal.ZERO); issue.setBonusAmount(BigDecimal.ONE); issue.setBonusMaxAmount(BigDecimal.ONE);
            issue.setRemoteRequestId(UUID.randomUUID().toString()); issue.setRemoteConfigurationId("history-"+n);
            issue.setRemoteReferenceId("history-"+n); issue.setRemoteLabelIdsJson("[123]"); issue.setWorkflowStatus("CREATED");
            entityManager.persist(issue);
        }
        batch.setExpectedCodeCount(1004);
        entityManager.flush(); entityManager.clear();
        var statistics = entityManagerFactory.unwrap(SessionFactory.class).getStatistics(); statistics.clear();
        var summary = service.batchSummaries().stream().filter(b -> prefix.equals(b.batch().operatorUsername())).findFirst().orElseThrow();
        assertThat(statistics.getPrepareStatementCount()).isEqualTo(3);
        assertThat(statistics.getCollectionFetchCount()).isZero();
        assertThat(summary.issueSummaries().stream().mapToInt(RedemptionDtos.IssueSummaryResponse::count).sum()).isEqualTo(1004);
        assertThat(summary.issueSummaries()).hasSizeLessThan(8);
        assertThat(summary.issueSummaries().stream().filter(RedemptionDtos.IssueSummaryResponse::creationNeedsReconciliation).mapToInt(RedemptionDtos.IssueSummaryResponse::count).sum()).isEqualTo(2);
        assertThat(summary.issueSummaries().stream().filter(RedemptionDtos.IssueSummaryResponse::creationAwaitingRemoteReview).mapToInt(RedemptionDtos.IssueSummaryResponse::count).sum()).isEqualTo(1);
        assertThat(summary.batch().createdCount()).isEqualTo(1000);
        assertThat(summary.batch().importedCount()).isEqualTo(2);
        var detail = service.batch(summary.batch().id());
        assertThat(detail.issues()).hasSize(1004);
        assertThat(mapper.writeValueAsBytes(summary).length).isLessThan(mapper.writeValueAsBytes(detail).length / 10);
        for (var row : mapper.valueToTree(summary).path("issueSummaries")) {
            assertThat(row.has("id")).isFalse(); assertThat(row.has("redemptionCode")).isFalse();
        }
        assertThat(summary.issueSummaries()).allSatisfy(row -> assertThat(row.remoteLabelIds()).containsExactly(123L));
    }

    @Test
    void publishedSummaryPreservesAllDownloadCandidateIdsWithoutIssueIdentities() {
        String prefix = seed(1);
        var batch = entityManager.createQuery("select b from RedemptionCodeBatch b, RedemptionCodeTask t where b.taskId=t.id and t.createdByUsername=:name", RedemptionCodeBatch.class)
                .setParameter("name", prefix).getSingleResult();
        entityManager.createNativeQuery("update erp_compat_redemption_code_batches set status='PUBLISHED' where id=:id")
                .setParameter("id", batch.getId()).executeUpdate();
        entityManager.flush(); entityManager.clear();
        var detail = service.batchOverviews().stream().filter(b -> prefix.equals(b.batch().operatorUsername())).findFirst().orElseThrow();
        var summary = service.batchSummaries().stream().filter(b -> prefix.equals(b.batch().operatorUsername())).findFirst().orElseThrow();
        assertThat(summary.issueSummaries().stream().flatMap(row -> row.configurationIds().stream()).toList())
                .containsExactlyInAnyOrderElementsOf(detail.issues().stream().filter(i -> !"CODE_IMPORTED".equals(i.workflowStatus()))
                        .map(RedemptionDtos.CodeIssueResponse::remoteConfigurationId).distinct().toList());
    }

    private String seed(int count) { return seed(count, false); }

    private String seed(int count, boolean reused) {
        String prefix = "list-" + UUID.randomUUID();
        LocalDate date = LocalDate.of(2099, 1, 1);
        for (int index = 0; index < count; index++) {
            var campaign = new RedemptionCampaign();
            campaign.setCode(prefix + "-" + index);
            campaign.setName("List query fixture");
            entityManager.persist(campaign);
            RedemptionCampaignTier first = null;
            for (int sort : List.of(2, 1, 0)) {
                var tier = new RedemptionCampaignTier();
                tier.setCampaignId(campaign.getId());
                tier.setDisplayName(List.of("first", "second", "third").get(sort));
                tier.setMinDepositAmount(BigDecimal.valueOf(sort));
                tier.setBonusAmount(BigDecimal.ONE);
                tier.setBonusMaxAmount(BigDecimal.ONE);
                tier.setSortOrder(sort);
                entityManager.persist(tier);
                first = tier;
            }
            var task = new RedemptionCodeTask();
            task.setGroupingKey(prefix + "-" + index);
            task.setTaskDate(date);
            task.setDailySequence(index + 1);
            task.setCreatedByUsername(prefix);
            entityManager.persist(task);
            var batch = new RedemptionCodeBatch();
            batch.setCampaignId(campaign.getId());
            batch.setTaskId(task.getId());
            batch.setSubtaskDate(date);
            batch.setSubtaskDailySequence(index + 1);
            batch.setClaimDateFrom(date);
            batch.setClaimDateTo(date.plusDays(3));
            batch.setLookbackDays(7);
            batch.setExpectedCodeCount(4);
            entityManager.persist(batch);
            RedemptionCodeIssue owner = null;
            for (int offset = 0; offset < 4; offset++) {
                var issue = new RedemptionCodeIssue();
                issue.setCampaignId(campaign.getId());
                issue.setRemoteMarketId(11L);
                issue.setCampaignTierId(first.getId());
                issue.setBatchId(batch.getId());
                issue.setClaimDate(date.plusDays(offset));
                issue.setDepositWindowStart(date.minusDays(7));
                issue.setDepositWindowEnd(date.minusDays(1));
                issue.setMinDepositAmount(BigDecimal.ZERO);
                issue.setBonusAmount(BigDecimal.ONE);
                issue.setBonusMaxAmount(BigDecimal.ONE);
                issue.setRemoteRequestId(UUID.randomUUID().toString());
                issue.setRemoteReferenceId("remote-reference");
                issue.setRemoteConfigurationId("remote-configuration-" + UUID.randomUUID());
                issue.setRemoteLabelIdsJson("[123]");
                issue.setRemoteGroupKey(UUID.randomUUID().toString());
                issue.setGeneratedAt(Instant.parse("2099-01-01T00:00:00Z"));
                issue.setState(offset == 2 ? "FAILED" : "GENERATED");
                issue.setWorkflowStatus(offset == 0 ? "CODE_IMPORTED" : offset == 2 ? "FAILED" : "CREATED");
                if (offset == 0) issue.setCodes(List.of(prefix + index + "-a", prefix + index + "-b"));
                if (offset == 0) owner = issue;
                if (reused && offset == 3) {
                    issue.setReusedFromIssue(owner);
                    issue.setRemoteConfigurationId(null);
                    issue.setRemoteReferenceId(null);
                    issue.setRemoteGroupKey(null);
                    issue.setState("PENDING");
                }
                entityManager.persist(issue);
                if (offset == 1) {
                    entityManager.flush();
                    // Historical rows can have only redemption_code and no collection entries.
                    entityManager.createNativeQuery("update erp_compat_redemption_code_issues set redemption_code = :code where id = :id")
                            .setParameter("code", prefix + index + "-legacy").setParameter("id", issue.getId()).executeUpdate();
                }
            }
        }
        entityManager.flush();
        entityManager.clear();
        return prefix;
    }
}
