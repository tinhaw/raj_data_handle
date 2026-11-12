package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.config.RemoteOperationGate;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
class RedemptionRemoteIdentityHttpTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired JdbcTemplate jdbc;
    @MockBean RemoteGiftCodeBackendClient standalone;
    @MockBean RemoteOperationGate gate;
    @MockBean UnifiedRedemptionRemoteExecutorClient executor;

    @org.junit.jupiter.api.BeforeEach
    void actualRewardReadback() {
        when(executor.checkReuse(anyLong(), anyLong(), anyString(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenAnswer(call -> new UnifiedRedemptionRemoteExecutorClient.ReuseCheck(call.getArgument(2), true,
                        java.util.List.of(), null, call.getArgument(8), call.getArgument(9)));
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"-1", "0"})
    void manualBindingCannotIntroduceInvalidConfigurationIds(String invalidId) throws Exception {
        var session = login();
        String suffix = java.util.UUID.randomUUID().toString().substring(0, 8);
        long market = market(session, "INVALID_BIND_" + suffix);
        account(session, market, "invalid-bind");
        var group = group(session, market, "INVALID_BIND_GROUP_" + suffix);
        long issue = group.at("/issues/0/id").asLong();
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issue + "/remote-configuration")
                .session(session).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                .content(mapper.writeValueAsString(java.util.Map.of("remoteConfigurationId", invalidId,
                        "rowVersion", group.at("/issues/0/rowVersion").asLong()))))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("INVALID_REMOTE_CONFIGURATION_ID"));
        assertThat(jdbc.queryForMap("select workflow_status,remote_configuration_id from erp_compat_redemption_code_issues where id=?", issue))
                .containsEntry("workflow_status", "PENDING_CREATION").containsEntry("remote_configuration_id", null);
        verifyNoInteractions(executor, standalone);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.NullAndEmptySource
    @org.junit.jupiter.params.provider.ValueSource(strings = {"-1", "0", "false"})
    void invalidCreateReceiptIsUnconfirmedAndCannotBeReplayed(String invalidId) throws Exception {
        var session = login();
        String suffix = java.util.UUID.randomUUID().toString().substring(0, 8);
        long market = market(session, "BAD_RECEIPT_" + suffix);
        account(session, market, "bad-receipt");
        var group = group(session, market, "BAD_RECEIPT_GROUP_" + suffix);
        long issue = group.at("/issues/0/id").asLong();
        when(executor.create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration(invalidId, null, null));
        create(session, issue, false).andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("REMOTE_CREATE_RESULT_UNCONFIRMED"));
        assertThat(jdbc.queryForMap("select workflow_status,remote_configuration_id,remote_reference_id,remote_create_receipt_id from erp_compat_redemption_code_issues where id=?", issue))
                .containsEntry("workflow_status", "FAILED").containsEntry("remote_configuration_id", null)
                .containsEntry("remote_reference_id", null).containsEntry("remote_create_receipt_id", null);
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/v1/redemption-campaigns/batches/" + group.at("/batch/id").asLong()).session(session))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].creationNeedsReconciliation").value(true));
        create(session, issue, true).andExpect(status().isConflict());
        verify(executor, times(1)).create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any());
        verifyNoInteractions(standalone);
    }

    @Test
    void historicalMinusOneRemainsUnchangedAndBlocksRecoveryPublishAndDownload() throws Exception {
        var session = login();
        long market = market(session, "HISTORICAL_MINUS_ONE");
        account(session, market, "historical-receipt");
        var group = group(session, market, "HISTORICAL_MINUS_ONE_GROUP");
        long issue = group.at("/issues/0/id").asLong();
        long batch = group.at("/batch/id").asLong();
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='CREATED',remote_configuration_id='-1',remote_reference_id='-1' where id=?", issue);
        jdbc.update("update erp_compat_redemption_code_batches set status='READY_TO_PUBLISH' where id=?", batch);
        var before = jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", issue);
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/v1/redemption-campaigns/batches/" + batch).session(session))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.createdCount").value(0))
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("CREATED"))
                .andExpect(jsonPath("$.data.issues[0].creationNeedsReconciliation").value(true));
        create(session, issue, true).andExpect(status().isConflict());
        long version = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, batch);
        mvc.perform(post("/api/v1/redemption-campaigns/batches/" + batch + "/remote-publish").session(session).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content("{\"mode\":\"IMMEDIATE\",\"fallbackToScheduled\":false,\"rowVersion\":" + version + "}"))
                .andExpect(status().isConflict());
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", issue)).isEqualTo(before);
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='FAILED',remote_configuration_id=null,remote_create_receipt_id='-1' where id=?", issue);
        create(session, issue, true).andExpect(status().isConflict());
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='PUBLISHED',remote_configuration_id='-1' where id=?", issue);
        jdbc.update("update erp_compat_redemption_code_batches set status='PUBLISHED',remote_publish_task_id='123' where id=?", batch);
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issue + "/remote-download").session(session).with(csrf()))
                .andExpect(status().isConflict());
        verifyNoInteractions(executor, standalone);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(booleans = {true, false})
    void uncertainCreateStopsSiblingMarketsAndDoesNotRewritePendingRows(boolean review) throws Exception {
        var session = login();
        String suffix = java.util.UUID.randomUUID().toString().substring(0, 8);
        long marketA = market(session, "REVIEW_A_" + suffix);
        long marketB = market(session, "REVIEW_B_" + suffix);
        account(session, marketA, "review-a");
        account(session, marketB, "review-b");
        var first = group(session, marketA, "REVIEW_FIRST_" + suffix);
        var second = group(session, marketB, "REVIEW_SECOND_" + suffix);
        long issue = first.at("/issues/0/id").asLong();
        long sibling = second.at("/issues/0/id").asLong();
        long batch = first.at("/batch/id").asLong();
        Long task = jdbc.queryForObject("select task_id from erp_compat_redemption_code_batches where id=?", Long.class, batch);
        jdbc.update("update erp_compat_redemption_code_batches set task_id=? where id=?", task, second.at("/batch/id").asLong());
        var untouched = jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", sibling);
        when(executor.create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenThrow(review ? RemoteConfigurationIds.awaitingReview() : RemoteConfigurationIds.unconfirmed());
        create(session, issue, false).andExpect(status().isConflict());
        var read = mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get(
                "/api/v1/redemption-campaigns/batches/" + batch).session(session))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.createdCount").value(0))
                .andExpect(jsonPath("$.data.issues[0].creationNeedsReconciliation").value(true));
        if (review) read.andExpect(jsonPath("$.data.issues[0].creationAwaitingRemoteReview").value(true));
        else read.andExpect(jsonPath("$.data.issues[0].creationAwaitingRemoteReview").doesNotExist());
        create(session, issue, true).andExpect(status().isConflict());
        create(session, sibling, false).andExpect(status().isConflict());
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", sibling)).isEqualTo(untouched);
        verify(executor, times(1)).create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any());
        verifyNoInteractions(standalone);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(booleans = {false, true})
    void storedSpecialCodeIsBlockedBeforeRemoteCallAcrossAccountsButNotMarkets(boolean collection) throws Exception {
        var session = login();
        String suffix = Boolean.toString(collection);
        long market = market(session, "DUPLICATE_CODE_" + suffix);
        account(session, market, "first-account");
        var old = group(session, market, "EXISTING_CODE_" + suffix);
        long oldIssue = old.at("/issues/0/id").asLong();
        if (collection) {
            jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)", oldIssue, 0, market, "OTHER-CODE");
            jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)", oldIssue, 1, market, "0905RAJ7DAYS0");
        } else jdbc.update("update erp_compat_redemption_code_issues set redemption_code='0905RAJ7DAYS0' where id=?", oldIssue);
        account(session, market, "second-account");
        var duplicate = group(session, market, "DUPLICATE_CODE_GROUP_" + suffix);
        long issue = duplicate.at("/issues/0/id").asLong();
        create(session, issue, false).andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("LOCAL_REDEMPTION_DUPLICATE"));
        assertThat(jdbc.queryForObject("select workflow_status from erp_compat_redemption_code_issues where id=?", String.class, issue)).isEqualTo("FAILED");
        verifyNoInteractions(executor, standalone);

        long otherMarket = market(session, "OTHER_CODE_" + suffix);
        account(session, otherMarket, "other-account");
        var allowed = group(session, otherMarket, "ALLOWED_CODE_GROUP_" + suffix);
        when(executor.create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("valid-other-id", null, null));
        create(session, allowed.at("/issues/0/id").asLong(), false).andExpect(status().isOk());
        verify(executor, times(1)).create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any());
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(booleans = {false, true})
    void missingConfigurationRepairRequiresFreshAbsenceAndNewPublicationBeforeDownload(boolean scheduled) throws Exception {
        var session = login();
        long market = market(session, "REPAIR_MARKET_" + scheduled);
        long accountId = account(session, market, "repair-account");
        var group = group(session, market, "REPAIR_GROUP_" + scheduled);
        register(session, group).andExpect(status().isOk());
        long batchId = group.at("/batch/id").asLong();
        long issueId = group.at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_batches set status='PUBLISHED',published_at=current_timestamp,remote_publish_mode='IMMEDIATE',remote_publish_task_id='old-task' where id=?", batchId);
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='PUBLISHED' where id=?", issueId);
        when(executor.verifyPublication(eq(accountId), eq(batchId), eq("old-task"), eq("test"), anyList()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublicationVerification("old-task", 4,
                        "COMPLETED", false, java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification(
                                "manual-scope-id", "MISSING")), java.time.Instant.now().toString(), null));
        long version = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, batchId);
        var repaired = send(session, "/api/v1/redemption-campaigns/batches/" + batchId + "/missing-configurations/repair",
                "{\"rowVersion\":" + version + "}");
        assertThat(repaired.at("/batch/status").asText()).isEqualTo("CREATING");
        assertThat(repaired.at("/issues/0/remoteConfigurationId").isNull()).isTrue();
        assertThat(repaired.at("/issues/0/remoteReferenceId").asText()).isEqualTo("manual-scope-id");
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issueId + "/remote-download").session(session).with(csrf()))
                .andExpect(status().isConflict());
        verify(executor, never()).download(anyLong(), anyLong(), anyString(), any(), anyInt());

        when(executor.create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("new-repair-id", "new-group", null));
        create(session, issueId, false).andExpect(status().isOk());
        assertThat(jdbc.queryForMap("select status,remote_publish_task_id from erp_compat_redemption_code_batches where id=?", batchId))
                .containsEntry("status", "CREATING").containsEntry("remote_publish_task_id", "old-task");
        java.time.LocalDateTime scheduledTime = null;
        if (scheduled) {
            // The fixture's fixed claim date is in the past. Extend only this fixture's
            // validity so both the expiry rejection and the valid schedule are testable.
            jdbc.update("update erp_compat_redemption_code_batches set valid_to_day_offset=365 where id=?", batchId);
            var tooLate = java.time.LocalDateTime.of(2027, 9, 6, 0, 0);
            version = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, batchId);
            mvc.perform(post("/api/v1/redemption-campaigns/batches/" + batchId + "/remote-publish")
                    .session(session).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                    .content(mapper.writeValueAsString(java.util.Map.of("rowVersion", version, "mode", "SCHEDULED",
                            "scheduledTime", tooLate.format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")),
                            "fallbackToScheduled", false))))
                    .andExpect(status().isBadRequest());
            verify(executor, never()).publish(anyLong(), anyLong(), anyString(), anyBoolean(), any(), anyBoolean());
            scheduledTime = java.time.LocalDateTime.now(java.time.ZoneId.of("Asia/Kolkata")).plusMinutes(30).withNano(0);
        }
        when(executor.publish(eq(accountId), eq(batchId), eq("test"), eq(scheduled),
                scheduled ? eq(scheduledTime) : isNull(), eq(false)))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublishedBatch("new-task", null));
        version = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, batchId);
        var publishRequest = new java.util.HashMap<String, Object>();
        publishRequest.put("rowVersion", version);
        publishRequest.put("mode", scheduled ? "SCHEDULED" : "IMMEDIATE");
        publishRequest.put("fallbackToScheduled", false);
        if (scheduled) publishRequest.put("scheduledTime", scheduledTime.format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")));
        var published = send(session, "/api/v1/redemption-campaigns/batches/" + batchId + "/remote-publish",
                mapper.writeValueAsString(publishRequest));
        assertThat(published.at("/batch/remotePublishTaskId").asText()).isEqualTo("new-task");
        assertThat(published.at("/issues/0/remoteConfigurationId").asText()).isEqualTo("new-repair-id");
        assertThat(published.at("/issues/0/workflowStatus").asText()).isEqualTo(scheduled ? "CREATED" : "PUBLISHED");
        verify(executor, times(1)).publish(eq(accountId), eq(batchId), eq("test"), eq(scheduled),
                scheduled ? eq(scheduledTime) : isNull(), eq(false));
        verifyNoInteractions(standalone);
    }

    @Test
    void sameIdAcrossMarketsWorksAndSameMarketAcrossAccountsReusesWithoutRecreation() throws Exception {
        MockHttpSession session = login();
        long marketA = market(session, "SCOPE_A");
        long accountA = account(session, marketA, "scope-a");
        long marketB = market(session, "SCOPE_B");
        account(session, marketB, "scope-b");
        long accountA2 = account(session, marketA, "scope-a-backup");
        JsonNode groupA = group(session, marketA, "SCOPE_GROUP_A");
        JsonNode groupB = group(session, marketB, "SCOPE_GROUP_B");
        JsonNode groupA2 = group(session, marketA, "SCOPE_GROUP_A2");
        long issueA = groupA.at("/issues/0/id").asLong();
        long issueB = groupB.at("/issues/0/id").asLong();
        long issueA2 = groupA2.at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_batches set remote_connection_id=? where id=?", accountA, groupA.at("/batch/id").asLong());
        jdbc.update("update erp_compat_redemption_code_batches set remote_connection_id=? where id=?", accountA2, groupA2.at("/batch/id").asLong());
        when(executor.create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("1632-scope", "group-scope", null));

        create(session, issueA, false).andExpect(status().isOk());
        create(session, issueB, false).andExpect(status().isOk());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_code_issues where remote_configuration_id='1632-scope'", Integer.class)).isEqualTo(2);
        // Database protection is necessary even when two workers pass a preflight simultaneously.
        assertThatThrownBy(() -> jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='1632-scope' where id=?", issueA2))
                .isInstanceOf(DataIntegrityViolationException.class);

        when(executor.checkReuse(eq(accountA2), eq(issueA2), eq("1632-scope"), anyString(), any(), any(), any(), anyList(), any(), any(), any(), anyString()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("1632-scope", true, java.util.List.of(), "group-scope", java.math.BigDecimal.ONE, java.math.BigDecimal.valueOf(3)));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+issueA2+"/reuse").session(session).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{\"rowVersion\":0}")).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.issues[0].reusedFromIssueId").value(issueA));
        assertThat(jdbc.queryForMap("select reused_from_issue_id,remote_configuration_id from erp_compat_redemption_code_issues where id=?", issueA2))
                .containsEntry("reused_from_issue_id", issueA).containsEntry("remote_configuration_id", null);
        create(session, issueA2, true).andExpect(status().isOk());
        verify(executor, times(2)).create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), eq("0905raj7days0"));
        verifyNoInteractions(standalone);
    }

    @Test
    void receiptRecoveryReadsActualRewardsWithoutRecreatingAndLegacyLostReceiptBlocksRetry() throws Exception {
        MockHttpSession session = login();
        long market = market(session, "RECEIPT_MARKET");
        account(session, market, "receipt-account");
        JsonNode group = group(session, market, "RECEIPT_GROUP");
        long issue = group.at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='FAILED', state='FAILED', remote_create_receipt_id='receipt-123', remote_error='registration failed' where id=?", issue);
        create(session, issue, true).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("CREATED"))
                .andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("receipt-123"));

        long legacy = group(session, market, "LOST_RECEIPT_GROUP").at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='FAILED', claim_date='2026-09-06', remote_error='duplicate key violates unique constraint remote_configuration_id' where id=?", legacy);
        create(session, legacy, true).andExpect(status().isConflict());
        verify(executor, times(1)).checkReuse(anyLong(), anyLong(), eq("receipt-123"), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any());
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        verifyNoInteractions(standalone);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"success", "rejected", "unavailable", "stale", "elapsed", "changed_market"})
    void cancellationUsesUnifiedExecutorAndPreservesStateUntilConfirmed(String scenario) throws Exception {
        MockHttpSession session = login();
        String prefix = "CANCEL_" + scenario.toUpperCase();
        long market = market(session, prefix);
        long account = account(session, market, prefix.toLowerCase());
        JsonNode group = group(session, market, prefix + "_GROUP");
        register(session, group).andExpect(status().isOk());
        long batchId = group.at("/batch/id").asLong();
        String path = "/api/v1/redemption-campaigns/batches/" + batchId;
        long version = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, batchId);
        when(executor.publish(anyLong(), anyLong(), anyString(), anyBoolean(), any(), anyBoolean()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublishedBatch("17717", null));
        String future = java.time.LocalDateTime.now(java.time.ZoneId.of("Asia/Kolkata")).plusHours(2)
                .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
        JsonNode scheduled = send(session, path + "/remote-publish", mapper.writeValueAsString(java.util.Map.of(
                "rowVersion", version, "mode", "SCHEDULED", "scheduledTime", future)));
        version = scheduled.at("/batch/rowVersion").asLong();
        // Production forbids the old client, but must still allow the unified cancellation path.
        doThrow(com.rajads.erp.shared.ApiException.forbidden("legacy client disabled")).when(gate).requireEnabled("remote_cancel");
        if (scenario.equals("rejected")) doThrow(com.rajads.erp.shared.ApiException.conflict("CANCEL_DENIED", "cancel denied"))
                .when(executor).cancelScheduledPublish(account, batchId, "17717");
        if (scenario.equals("unavailable")) doThrow(new com.rajads.erp.identity.CompatibilityIdentityUnavailableException("cancel unavailable"))
                .when(executor).cancelScheduledPublish(account, batchId, "17717");
        if (scenario.equals("elapsed")) jdbc.update("update erp_compat_redemption_code_batches set remote_scheduled_publish_at=? where id=?",
                java.time.LocalDateTime.now(java.time.ZoneId.of("Asia/Kolkata")).minusHours(1), batchId);
        if (scenario.equals("changed_market")) {
            long otherMarket = market(session, prefix + "_OTHER");
            long otherAccount = account(session, otherMarket, prefix.toLowerCase() + "-other");
            jdbc.update("update erp_compat_redemption_code_batches set remote_connection_id=? where id=?", otherAccount, batchId);
        }
        clearInvocations(executor);
        var result = mvc.perform(post(path + "/remote-publish/cancel").session(session).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(java.util.Map.of(
                        "rowVersion", scenario.equals("stale") ? version - 1 : version))));
        if (scenario.equals("success")) {
            result.andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("READY_TO_PUBLISH"));
            assertThat(jdbc.queryForObject("select remote_publish_task_id from erp_compat_redemption_code_batches where id=?", String.class, batchId)).isNull();
            long cancelledVersion = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, batchId);
            JsonNode published = send(session, path + "/remote-publish", mapper.writeValueAsString(java.util.Map.of(
                    "rowVersion", cancelledVersion, "mode", "IMMEDIATE", "fallbackToScheduled", false)));
            assertThat(published.at("/batch/remotePublishMode").asText()).isEqualTo("IMMEDIATE");
            assertThat(published.at("/issues/0/workflowStatus").asText()).isEqualTo("PUBLISHED");
        } else {
            if (scenario.equals("unavailable")) result.andExpect(status().isServiceUnavailable());
            else result.andExpect(status().isConflict());
            assertThat(jdbc.queryForMap("select status,remote_publish_mode,remote_publish_task_id from erp_compat_redemption_code_batches where id=?", batchId))
                    .containsEntry("status", "PUBLISHED").containsEntry("remote_publish_mode", "SCHEDULED").containsEntry("remote_publish_task_id", "17717");
        }
        if (java.util.Set.of("stale", "elapsed", "changed_market").contains(scenario)) verifyNoInteractions(executor);
        else verify(executor).cancelScheduledPublish(account, batchId, "17717");
        verifyNoInteractions(standalone, gate);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings = {"waiting", "missing", "success", "empty", "unavailable", "race"})
    void downloadRequiresActualPublicationAndMatchingConfiguration(String scenario) throws Exception {
        var session = login();
        String prefix = "VERIFY_" + scenario.toUpperCase();
        long market = market(session, prefix);
        long accountId = account(session, market, prefix.toLowerCase());
        var group = group(session, market, prefix + "_GROUP");
        register(session, group).andExpect(status().isOk());
        long batchId = group.at("/batch/id").asLong();
        long issueId = group.at("/issues/0/id").asLong();
        // Local time is deliberately in the past for WAITING and the future for COMPLETED.
        jdbc.update("update erp_compat_redemption_code_batches set status='PUBLISHED',remote_publish_mode='SCHEDULED',remote_publish_task_id='222',remote_scheduled_publish_at=? where id=?",
                java.time.LocalDateTime.now(java.time.ZoneId.of("Asia/Kolkata")).plusHours(scenario.equals("waiting") ? -1 : 1), batchId);
        jdbc.update("update erp_compat_redemption_code_issues set remote_group_key='group-174' where id=?", issueId);
        var configs = java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification(
                "manual-scope-id", scenario.equals("missing") ? "MISSING" : "MATCHED"));
        var verification = new UnifiedRedemptionRemoteExecutorClient.PublicationVerification("222", scenario.equals("waiting") ? 0 : 4,
                scenario.equals("waiting") ? "WAITING" : "COMPLETED", scenario.equals("waiting"), configs, java.time.Instant.now().toString(), null);
        when(executor.verifyPublication(eq(accountId), eq(batchId), eq("222"), eq("test"), anyList())).thenReturn(verification);
        if (scenario.equals("unavailable")) when(executor.verifyPublication(anyLong(), anyLong(), anyString(), anyString(), anyList()))
                .thenThrow(new com.rajads.erp.identity.CompatibilityIdentityUnavailableException("verification unavailable"));
        if (scenario.equals("race")) when(executor.verifyPublication(anyLong(), anyLong(), anyString(), anyString(), anyList()))
                .thenAnswer(invocation -> { jdbc.update("update erp_compat_redemption_code_batches set remote_publish_task_id='223' where id=?", batchId); return verification; });
        when(executor.download(anyLong(), anyLong(), anyString(), any(), anyInt()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.DownloadedCodes(java.util.List.of("CODE-VERIFY-1"), "group-174"));
        if (scenario.equals("empty")) when(executor.download(anyLong(), anyLong(), anyString(), any(), anyInt()))
                .thenThrow(com.rajads.erp.shared.ApiException.badRequest("EMPTY_CODES", "远端兑换码文件应包含 1 个兑换码，实际 0 个。"));
        var action = mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issueId + "/remote-download").session(session).with(csrf()));
        if (scenario.equals("success")) action.andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("COMPLETED"));
        else if (scenario.equals("unavailable")) action.andExpect(status().isServiceUnavailable());
        else if (scenario.equals("empty")) action.andExpect(status().isBadRequest());
        else action.andExpect(status().isConflict());
        String expected = scenario.equals("success") ? "CODE_IMPORTED" : scenario.equals("empty") ? "PUBLISHED" : "CREATED";
        assertThat(jdbc.queryForObject("select workflow_status from erp_compat_redemption_code_issues where id=?", String.class, issueId)).isEqualTo(expected);
        if (!java.util.Set.of("success", "empty").contains(scenario)) verify(executor, never()).download(anyLong(), anyLong(), anyString(), any(), anyInt());
        verify(executor).verifyPublication(eq(accountId), eq(batchId), eq("222"), eq("test"), anyList());
        verifyNoInteractions(standalone, gate);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(ints = {1, 50})
    void codeValuesAreScopedToMarketAndDuplicateImportsRemainAtomic(int keyNumber) throws Exception {
        var session = login();
        String prefix = "CODE_SCOPE_" + keyNumber;
        long marketA = market(session, prefix + "_A");
        long accountA = account(session, marketA, prefix.toLowerCase() + "-a");
        long marketB = market(session, prefix + "_B");
        long accountB = account(session, marketB, prefix.toLowerCase() + "-b");
        var groups = java.util.List.of(group(session, marketA, prefix + "_GROUP_A", keyNumber),
                group(session, marketB, prefix + "_GROUP_B", keyNumber),
                group(session, marketA, prefix + "_GROUP_C", keyNumber));
        var codes = java.util.stream.IntStream.range(0, keyNumber)
                .mapToObj(i -> prefix + "-SHARED-" + i).toList();
        for (int index = 0; index < groups.size(); index++) {
            var group = groups.get(index);
            long batch = group.at("/batch/id").asLong();
            long issue = group.at("/issues/0/id").asLong();
            long account = index == 1 ? accountB : accountA;
            String config = "code-scope-" + index;
            mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issue + "/remote-configuration")
                    .session(session).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                    .content("{\"remoteConfigurationId\":\"" + config + "\",\"rowVersion\":" + group.at("/issues/0/rowVersion").asLong() + "}"))
                    .andExpect(status().isOk());
            String task = "scope-task-" + index;
            jdbc.update("update erp_compat_redemption_code_batches set status='PUBLISHED',remote_publish_mode='IMMEDIATE',remote_publish_task_id=? where id=?", task, batch);
            var check = new UnifiedRedemptionRemoteExecutorClient.PublicationVerification(task, 4, "COMPLETED", false,
                    java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification(config, "MATCHED")),
                    java.time.Instant.now().toString(), null);
            when(executor.verifyPublication(eq(account), eq(batch), eq(task), eq("test"), anyList())).thenReturn(check);
            when(executor.download(eq(account), eq(issue), eq(config), any(), eq(keyNumber)))
                    .thenReturn(new UnifiedRedemptionRemoteExecutorClient.DownloadedCodes(codes, "scope-group-" + index));
            var action = mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issue + "/remote-download").session(session).with(csrf()));
            if (index < 2) action.andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("COMPLETED"))
                    .andExpect(jsonPath("$.data.issues[0].redemptionCodes.length()").value(keyNumber));
            else action.andExpect(status().isConflict());
        }
        long issueA = groups.get(0).at("/issues/0/id").asLong();
        long issueB = groups.get(1).at("/issues/0/id").asLong();
        long issueC = groups.get(2).at("/issues/0/id").asLong();
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id in (?,?)", Integer.class, issueA, issueB)).isEqualTo(2 * keyNumber);
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?", Integer.class, issueC)).isZero();
        // Migration 0061 scopes persisted values to the configuration owner/generation.
        assertThat(jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,code,remote_market_id) values(?,0,?,?)",
                issueC, codes.get(0), marketA)).isEqualTo(1);
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> jdbc.update(
                "insert into erp_compat_redemption_issue_codes(issue_id,code_index,code,remote_market_id) values(?,1,?,?)", issueC, codes.get(0), marketA))
                .isInstanceOf(DataIntegrityViolationException.class);
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> jdbc.update(
                "insert into erp_compat_redemption_issue_codes(issue_id,code_index,code,remote_market_id) values(?,0,?,?)", issueC, prefix + "-WRONG-MARKET", marketB))
                .isInstanceOf(DataIntegrityViolationException.class);
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issueA + "/remote-download").session(session).with(csrf()))
                .andExpect(status().isOk());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?", Integer.class, issueA)).isEqualTo(keyNumber);
        verifyNoInteractions(standalone, gate);
    }

    private org.springframework.test.web.servlet.ResultActions create(MockHttpSession session, long issue, boolean retry) throws Exception {
        return mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issue + "/remote-create")
                .param("retryFailed", Boolean.toString(retry)).session(session).with(csrf()));
    }

    @Test
    void manualRegistrationIsMarketScopedAndChangedAccountCannotPublishOrDownload() throws Exception {
        MockHttpSession session = login();
        long marketA = market(session, "MANUAL_SCOPE_A");
        account(session, marketA, "manual-a");
        long marketB = market(session, "MANUAL_SCOPE_B");
        long accountB = account(session, marketB, "manual-b");
        JsonNode groupA = group(session, marketA, "MANUAL_SCOPE_GROUP_A");
        JsonNode groupB = group(session, marketB, "MANUAL_SCOPE_GROUP_B");
        JsonNode duplicate = group(session, marketA, "MANUAL_SCOPE_DUPLICATE");
        register(session, groupA).andExpect(status().isOk());
        register(session, groupB).andExpect(status().isOk());
        register(session, duplicate).andExpect(status().isConflict());

        long batchA = groupA.at("/batch/id").asLong();
        long issueA = groupA.at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_batches set remote_connection_id=? where id=?", accountB, batchA);
        long version = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, batchA);
        mvc.perform(post("/api/v1/redemption-campaigns/batches/" + batchA + "/remote-publish")
                        .session(session).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"mode\":\"IMMEDIATE\",\"rowVersion\":" + version + ",\"fallbackToScheduled\":false}"))
                .andExpect(status().isConflict());
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='PUBLISHED' where id=?", issueA);
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issueA + "/remote-download").session(session).with(csrf()))
                .andExpect(status().isConflict());
        verifyNoInteractions(executor, standalone);
    }

    private org.springframework.test.web.servlet.ResultActions register(MockHttpSession session, JsonNode group) throws Exception {
        return mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + group.at("/issues/0/id").asLong() + "/remote-configuration")
                .session(session).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                .content("{\"remoteConfigurationId\":\"manual-scope-id\",\"rowVersion\":" + group.at("/issues/0/rowVersion").asLong() + "}"));
    }

    private long market(MockHttpSession session, String code) throws Exception {
        return send(session, "/api/v1/redemption-remote-markets", """
                {"code":"%s","name":"%s","baseUrl":"https://%s.example","enabled":true}
                """.formatted(code, code, code.toLowerCase().replace('_', '-'))).path("id").asLong();
    }

    private long account(MockHttpSession session, long market, String username) throws Exception {
        return send(session, "/api/v1/redemption-remote-connections", """
                {"username":"%s","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                """.formatted(username, market)).path("id").asLong();
    }

    private JsonNode group(MockHttpSession session, long market, String code) throws Exception {
        return group(session, market, code, 1);
    }

    private JsonNode group(MockHttpSession session, long market, String code, int keyNumber) throws Exception {
        return send(session, "/api/v1/redemption-campaigns/groups", """
                {"code":"%s","name":"%s","claimDateFrom":"2026-09-05","claimDateTo":"2026-09-05","lookbackDays":7,
                 "tiers":[{"displayName":"全部用户","minDepositAmount":0,"bonusAmount":1,"bonusMaxAmount":3,"sortOrder":1}],
                 "remoteMarketId":%s,"redemptionType":"%s","tierUserTypes":["ALL_USERS"],"tierLabelIds":[[]],
                 "remoteOptions":{"publishEnvironment":"test","flowTimes":5,"creationIntervalSeconds":5,"keyNumber":%d,"singleUserLimit":1,"singleKeyLimit":2,"requireBindBankCard":false,"requireBindPhone":true,"checkUuid":true,"uuidRewardLimit":1,"checkLoginIp":true,"loginIpRewardLimit":1,"checkRegisterIp":true,"registerIpRewardLimit":1}}
                """.formatted(code, code, market, keyNumber == 1 ? "SEVEN_DAY_DEPOSIT" : "AGENT", keyNumber));
    }

    private JsonNode send(MockHttpSession session, String path, String content) throws Exception {
        MvcResult result = mvc.perform(post(path).session(session).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(content))
                .andExpect(status().isOk()).andReturn();
        return mapper.readTree(result.getResponse().getContentAsString()).path("data");
    }

    private MockHttpSession login() throws Exception {
        return (MockHttpSession) mvc.perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON)
                .content("{\"username\":\"admin\",\"password\":\"admin123\"}"))
                .andExpect(status().isOk()).andReturn().getRequest().getSession(false);
    }
}
