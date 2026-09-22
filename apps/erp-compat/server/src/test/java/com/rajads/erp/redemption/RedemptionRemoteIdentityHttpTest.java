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

    @Test
    void missingConfigurationRepairRequiresFreshAbsenceAndNewPublicationBeforeDownload() throws Exception {
        var session = login();
        long market = market(session, "REPAIR_MARKET");
        long accountId = account(session, market, "repair-account");
        var group = group(session, market, "REPAIR_GROUP");
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

        when(executor.create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("new-repair-id", "new-group", null));
        create(session, issueId, false).andExpect(status().isOk());
        assertThat(jdbc.queryForMap("select status,remote_publish_task_id from erp_compat_redemption_code_batches where id=?", batchId))
                .containsEntry("status", "CREATING").containsEntry("remote_publish_task_id", "old-task");
        when(executor.publish(eq(accountId), eq(batchId), eq("test"), eq(false), isNull(), eq(false)))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublishedBatch("new-task", null));
        version = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, batchId);
        var published = send(session, "/api/v1/redemption-campaigns/batches/" + batchId + "/remote-publish",
                "{\"rowVersion\":" + version + ",\"mode\":\"IMMEDIATE\",\"fallbackToScheduled\":false}");
        assertThat(published.at("/batch/remotePublishTaskId").asText()).isEqualTo("new-task");
        assertThat(published.at("/issues/0/remoteConfigurationId").asText()).isEqualTo("new-repair-id");
        assertThat(published.at("/issues/0/workflowStatus").asText()).isEqualTo("PUBLISHED");
        verifyNoInteractions(standalone);
    }

    @Test
    void sameIdAcrossMarketsWorksButSameMarketAcrossAccountsConflictsWithoutRecreation() throws Exception {
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
        when(executor.create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("1632-scope", "group-scope", null));

        create(session, issueA, false).andExpect(status().isOk());
        create(session, issueB, false).andExpect(status().isOk());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_code_issues where remote_configuration_id='1632-scope'", Integer.class)).isEqualTo(2);
        // Database protection is necessary even when two workers pass a preflight simultaneously.
        assertThatThrownBy(() -> jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='1632-scope' where id=?", issueA2))
                .isInstanceOf(DataIntegrityViolationException.class);

        create(session, issueA2, false).andExpect(status().isConflict());
        assertThat(jdbc.queryForMap("select workflow_status,remote_reference_id,remote_configuration_id from erp_compat_redemption_code_issues where id=?", issueA2))
                .containsEntry("workflow_status", "FAILED").containsEntry("remote_reference_id", "1632-scope")
                .containsEntry("remote_configuration_id", null);
        create(session, issueA2, true).andExpect(status().isConflict());
        verify(executor, times(3)).create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any());
        verifyNoInteractions(standalone);
    }

    @Test
    void receiptRecoveryOnlyRegistersLocallyAndLegacyLostReceiptBlocksRetry() throws Exception {
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
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='FAILED', remote_error='duplicate key violates unique constraint remote_configuration_id' where id=?", legacy);
        create(session, legacy, true).andExpect(status().isConflict());
        verifyNoInteractions(executor, standalone);
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
        return send(session, "/api/v1/redemption-campaigns/groups", """
                {"code":"%s","name":"%s","claimDateFrom":"2026-09-05","claimDateTo":"2026-09-05","lookbackDays":7,
                 "tiers":[{"displayName":"全部用户","minDepositAmount":0,"bonusAmount":1,"bonusMaxAmount":3,"sortOrder":1}],
                 "remoteMarketId":%s,"redemptionType":"SEVEN_DAY_DEPOSIT","tierUserTypes":["ALL_USERS"],"tierLabelIds":[[]],
                 "remoteOptions":{"publishEnvironment":"test","flowTimes":5,"creationIntervalSeconds":5,"keyNumber":1,"singleUserLimit":1,"singleKeyLimit":2,"requireBindBankCard":false,"requireBindPhone":true,"checkUuid":true,"uuidRewardLimit":1,"checkLoginIp":true,"loginIpRewardLimit":1,"checkRegisterIp":true,"registerIpRewardLimit":1}}
                """.formatted(code, code, market));
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
