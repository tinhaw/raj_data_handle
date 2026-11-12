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

@SpringBootTest(properties = "spring.jpa.open-in-view=false")
@AutoConfigureMockMvc
class RedemptionReuseHttpTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired JdbcTemplate jdbc;
    @Autowired RedemptionReuseService reuseService;
    @MockBean RemoteGiftCodeBackendClient standalone;
    @MockBean RemoteOperationGate gate;
    @MockBean UnifiedRedemptionRemoteExecutorClient executor;


    private record Pair(MockHttpSession session, long market, long account, JsonNode original, JsonNode repeated) {
        long owner() { return original.at("/issues/0/id").asLong(); }
        long alias() { return repeated.at("/issues/0/id").asLong(); }
        long originalBatch() { return original.at("/batch/id").asLong(); }
        long repeatedBatch() { return repeated.at("/batch/id").asLong(); }
    }

    private Pair pair(String name) throws Exception {
        var session = login();
        long market = market(session, "REUSE_" + name);
        long account = account(session, market, "reuse-" + name.toLowerCase());
        var original = group(session, market, "OWNER_" + name);
        var repeated = group(session, market, "ALIAS_" + name);
        var pair = new Pair(session, market, account, original, repeated);
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='3403',remote_reference_id='3403',remote_group_key='group-3403',workflow_status='CREATED' where id=?", pair.owner());
        when(executor.checkReuse(anyLong(), anyLong(), eq("3403"), anyString(), any(), any(), any(), anyList(), any(), any(), any(), anyString()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403", true, java.util.List.of(), "group-3403", java.math.BigDecimal.ONE, java.math.BigDecimal.valueOf(3)));
        return pair;
    }

    private org.springframework.test.web.servlet.ResultActions create(Pair p) throws Exception {
        return mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/reuse")
                .session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                .content("{\"rowVersion\":" + jdbc.queryForObject("select row_version from erp_compat_redemption_code_issues where id=?", Long.class, p.alias()) + "}"));
    }

    private org.springframework.test.web.servlet.ResultActions detail(Pair p, long batch) throws Exception {
        return mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/v1/redemption-campaigns/batches/" + batch).session(p.session()));
    }

    @Test void selectedConfigurationDisambiguatesHistoryWithoutChangingOtherOwner() throws Exception {
        var p=pair("SELECTED");var second=group(p.session(),p.market(),"SELECTED_OTHER");long secondId=second.at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='3410',remote_group_key='other-group',workflow_status='CREATED' where id=?",secondId);
        var before=jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?",secondId);
        create(p).andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REUSE_AMBIGUOUS_CONFIGURATION"))
            .andExpect(jsonPath("$.details.candidates.length()").value(2));
        long version=jdbc.queryForObject("select row_version from erp_compat_redemption_code_issues where id=?",Long.class,p.alias());
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+p.alias()+"/reuse").session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
            .content(mapper.writeValueAsString(java.util.Map.of("rowVersion",version,"configurationId","3403"))))
            .andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].reusedFromIssueId").value(p.owner()));
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?",secondId)).isEqualTo(before);
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        verify(executor,never()).checkReuse(anyLong(),anyLong(),eq("3410"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),anyString());
    }
    @Test void selectedOwnerCannotBypassDeletionHoldOrParameterMismatch() throws Exception {
        var p=pair("SELECTED_HELD");
        jdbc.update("update erp_compat_redemption_code_issues set remote_deletion_state='UNKNOWN' where id=?",p.owner());
        String body=mapper.writeValueAsString(java.util.Map.of("rowVersion",p.repeated().at("/issues/0/rowVersion").asLong(),"configurationId","3403"));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+p.alias()+"/reuse").session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(body))
            .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REMOTE_CONFIGURATION_DELETION_HELD"));
        verifyNoInteractions(executor);
        jdbc.update("update erp_compat_redemption_code_issues set remote_deletion_state=null where id=?",p.owner());
        when(executor.checkReuse(anyLong(),anyLong(),eq("3403"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),anyString()))
            .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403",false,java.util.List.of("single_key_limit"),"group-3403",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(3)));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+p.alias()+"/reuse").session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(body))
            .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REUSE_SELECTED_CONFIGURATION_MISMATCH"));
        assertThat(jdbc.queryForObject("select reused_from_issue_id from erp_compat_redemption_code_issues where id=?",Long.class,p.alias())).isNull();
    }

    @Test
    void completedConfigurationIsReusedWithoutDuplicateInventoryAndRemainsExportable() throws Exception {
        var p = pair("IMPORTED");
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='CODE_IMPORTED',state='GENERATED',redemption_code='0905RAJ7DAYS0' where id=?", p.owner());
        jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)", p.owner(), 0, p.market(), "0905RAJ7DAYS0");
        var original = jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", p.owner());
        create(p).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.status").value("COMPLETED"))
                .andExpect(jsonPath("$.data.issues[0].reusedFromIssueId").value(p.owner()))
                .andExpect(jsonPath("$.data.issues[0].redemptionCodes[0]").value("0905RAJ7DAYS0"))
                .andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("3403"));
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", p.owner())).isEqualTo(original);
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id in (?,?)", Integer.class, p.owner(), p.alias())).isEqualTo(1);
        assertThat(jdbc.queryForMap("select remote_configuration_id,reused_from_issue_id,redemption_code from erp_compat_redemption_code_issues where id=?", p.alias()))
                .containsEntry("remote_configuration_id", null).containsEntry("redemption_code", null).containsEntry("reused_from_issue_id", p.owner());
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/remote-download").session(p.session()).with(csrf())).andExpect(status().isOk());
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        verify(executor, never()).download(any(), any(), any(), any(), anyInt());
        verifyNoInteractions(standalone);
    }

    @Test
    void createdConfigurationCanBePublishedThroughAliasAndDownloadedOnceThroughOriginal() throws Exception {
        var p = pair("PUBLISH");
        create(p).andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("READY_TO_PUBLISH"));
        long version = jdbc.queryForObject("select row_version from erp_compat_redemption_code_batches where id=?", Long.class, p.repeatedBatch());
        when(executor.publish(eq(p.account()), eq(p.repeatedBatch()), eq("test"), eq(false), isNull(), eq(false)))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublishedBatch("publish-1", null));
        mvc.perform(post("/api/v1/redemption-campaigns/batches/" + p.repeatedBatch() + "/remote-publish").session(p.session()).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content("{\"mode\":\"IMMEDIATE\",\"fallbackToScheduled\":false,\"rowVersion\":" + version + "}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].workflowStatus").value("PUBLISHED"));
        when(executor.verifyPublication(eq(p.account()), eq(p.repeatedBatch()), eq("publish-1"), eq("test"), anyList()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublicationVerification("publish-1", 2, "COMPLETED", false,
                        java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification("3403", "MATCHED")), "2026-09-05T00:00:00Z", null));
        when(executor.download(eq(p.account()), eq(p.owner()), eq("3403"), eq("group-3403"), eq(1)))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.DownloadedCodes(java.util.List.of("0905raj7days0"), "group-3403"));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.owner() + "/remote-download").session(p.session()).with(csrf()))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("COMPLETED"));
        detail(p, p.repeatedBatch()).andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("COMPLETED"))
                .andExpect(jsonPath("$.data.issues[0].redemptionCode").value("0905raj7days0"));
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id in (?,?)", Integer.class, p.owner(), p.alias())).isEqualTo(1);
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    void aliasDownloadsOriginalPublicationWithoutOpenSessionAndClearsPreviousFailure() throws Exception {
        var p = pair("ALIAS_DOWNLOAD");
        create(p).andExpect(status().isOk());
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='PUBLISHED' where id=?", p.owner());
        jdbc.update("update erp_compat_redemption_code_batches set status='PUBLISHED',remote_publish_task_id='owner-publish' where id=?", p.originalBatch());
        jdbc.update("update erp_compat_redemption_code_issues set remote_error='previous download failure' where id=?", p.alias());
        when(executor.verifyPublication(eq(p.account()), eq(p.originalBatch()), eq("owner-publish"), eq("test"), anyList()))
                .thenAnswer(invocation -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
                    return new UnifiedRedemptionRemoteExecutorClient.PublicationVerification("owner-publish", 2, "COMPLETED", false,
                            java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification("3403", "MATCHED")), "2026-09-05T00:00:00Z", null);
                });
        when(executor.download(eq(p.account()), eq(p.alias()), eq("3403"), eq("group-3403"), eq(1)))
                .thenAnswer(invocation -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
                    return new UnifiedRedemptionRemoteExecutorClient.DownloadedCodes(java.util.List.of("0905raj7days0"), "group-3403");
                });
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/remote-download").session(p.session()).with(csrf()))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("COMPLETED"))
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("CODE_IMPORTED"))
                .andExpect(jsonPath("$.data.issues[0].remoteError").doesNotExist());
        detail(p, p.originalBatch()).andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("COMPLETED"))
                .andExpect(jsonPath("$.data.issues[0].redemptionCode").value("0905raj7days0"));
        // Retrying an imported alias must use the owner's inventory without another export.
        jdbc.update("update erp_compat_redemption_code_issues set remote_error='stale alias error' where id=?", p.alias());
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/remote-download").session(p.session()).with(csrf()))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].remoteError").doesNotExist());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?", Integer.class, p.owner())).isEqualTo(1);
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?", Integer.class, p.alias())).isZero();
        assertThat(jdbc.queryForMap("select remote_configuration_id,reused_from_issue_id,redemption_code,remote_error from erp_compat_redemption_code_issues where id=?", p.alias()))
                .containsEntry("remote_configuration_id", null).containsEntry("reused_from_issue_id", p.owner())
                .containsEntry("redemption_code", null).containsEntry("remote_error", null);
        verify(executor, times(1)).download(any(), any(), any(), any(), anyInt());
        verify(executor, times(1)).verifyPublication(any(), any(), any(), any(), anyList());
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        verify(executor, never()).publish(any(), any(), any(), anyBoolean(), any(), anyBoolean());
        verifyNoInteractions(standalone);
    }

    @Test
    void aliasStillRequiresMatchingOriginalConfigurationBeforeDownload() throws Exception {
        var p = pair("ALIAS_MISMATCH");
        create(p).andExpect(status().isOk());
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='PUBLISHED' where id=?", p.owner());
        jdbc.update("update erp_compat_redemption_code_batches set status='PUBLISHED',remote_publish_task_id='missing-owner' where id=?", p.originalBatch());
        when(executor.verifyPublication(eq(p.account()), eq(p.originalBatch()), eq("missing-owner"), eq("test"), anyList()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublicationVerification("missing-owner", 2, "COMPLETED", false,
                        java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification("3403", "MISSING")), "2026-09-05T00:00:00Z", null));
        var ownerBefore = jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", p.owner());
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/remote-download").session(p.session()).with(csrf()))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REMOTE_CONFIGURATION_MISMATCH"));
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", p.owner())).isEqualTo(ownerBefore);
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id in (?,?)", Integer.class, p.owner(), p.alias())).isZero();
        verify(executor, never()).download(any(), any(), any(), any(), anyInt());
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        verify(executor, never()).publish(any(), any(), any(), anyBoolean(), any(), anyBoolean());
    }

    @Test
    void nonRewardDifferencesStillAllowReuseWithoutModifyingExistingConfiguration() throws Exception {
        var p = pair("LIMIT");
        jdbc.update("update erp_compat_redemption_code_batches set remote_single_key_limit=3,remote_publish_environment='prod' where id=?", p.repeatedBatch());
        var original = jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", p.owner());
        when(executor.checkReuse(anyLong(), eq(p.alias()), anyString(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), anyString()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403", false,
                        java.util.List.of("single_key_limit", "label_array", "valid_time", "status"), "group-3403", java.math.BigDecimal.ONE, java.math.BigDecimal.valueOf(3)));
        create(p).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.issues[0].reusedFromIssueId").value(p.owner()))
                .andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("3403"))
                .andExpect(jsonPath("$.data.batch.remoteOptions.singleKeyLimit").value(3));
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", p.owner())).isEqualTo(original);
        assertThat(jdbc.queryForObject("select after_json from erp_compat_audit_logs where action='REDEMPTION_CONFIGURATION_REUSED' and entity_id=? order by id desc limit 1", String.class, Long.toString(p.alias())))
                .contains("single_key_limit", "EXISTING_REMOTE_CONFIGURATION", "requestedSingleKeyLimit");
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        verifyNoInteractions(standalone);
    }

    @Test
    void aDifferentRemoteCodeStillCannotBeLinkedAsTheRequestedConfiguration() throws Exception {
        var p = pair("CODE_IDENTITY");
        when(executor.checkReuse(anyLong(), eq(p.alias()), anyString(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), anyString()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403", false, java.util.List.of("gift_code")));
        create(p).andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("REUSE_CONFIGURATION_IDENTITY_MISMATCH"));
        assertThat(jdbc.queryForObject("select reused_from_issue_id from erp_compat_redemption_code_issues where id=?", Long.class, p.alias())).isNull();
        assertThat(jdbc.queryForObject("select workflow_status from erp_compat_redemption_code_issues where id=?", String.class, p.alias())).isEqualTo("PENDING_CREATION");
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    void unresolvedMinusOneCanBeLinkedOnlyAfterLiveMatchAndKeepsItsTaskIdentity() throws Exception {
        var p = pair("UNRESOLVED");
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='-1',remote_reference_id='-1',workflow_status='CREATED' where id=?", p.alias());
        long taskId = p.repeated().at("/batch/taskId").asLong();
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/reuse").session(p.session()).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content("{\"rowVersion\":0}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.taskId").value(taskId))
                .andExpect(jsonPath("$.data.issues[0].creationNeedsReconciliation").doesNotExist())
                .andExpect(jsonPath("$.data.issues[0].reusedFromIssueId").value(p.owner()));
        assertThat(jdbc.queryForMap("select remote_configuration_id,remote_reference_id from erp_compat_redemption_code_issues where id=?", p.alias()))
                .containsEntry("remote_configuration_id", null).containsEntry("remote_reference_id", null);
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.owner() + "/remote-configuration").session(p.session()).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content("{\"remoteConfigurationId\":\"999\",\"rowVersion\":0}"))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("SHARED_CONFIGURATION_LOCKED"));
    }

    @Test
    void concurrentChangeDuringReadLeavesTargetUnlinked() throws Exception {
        var p = pair("STALE");
        when(executor.checkReuse(anyLong(), eq(p.alias()), anyString(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), anyString()))
                .thenAnswer(invocation -> {
                    jdbc.update("update erp_compat_redemption_code_issues set row_version=row_version+1 where id=?", p.alias());
                    return new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403", true, java.util.List.of(), "group-3403", java.math.BigDecimal.ONE, java.math.BigDecimal.valueOf(3));
                });
        create(p).andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REUSE_STATE_CHANGED"));
        assertThat(jdbc.queryForObject("select reused_from_issue_id from erp_compat_redemption_code_issues where id=?", Long.class, p.alias())).isNull();
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    void disablingNewLinksPreservesExistingAssociationsAndCodeReads() throws Exception {
        var p = pair("DISABLED");
        create(p).andExpect(status().isOk());
        var another = group(p.session(), p.market(), "NEW_DISABLED_ALIAS");
        org.springframework.test.util.ReflectionTestUtils.setField(reuseService, "newAssociationsEnabled", false);
        try {
            create(p).andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].reusedFromIssueId").value(p.owner()));
            mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + another.at("/issues/0/id").asLong() + "/reuse")
                    .session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{\"rowVersion\":0}")).andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REUSE_DISABLED"));
            detail(p, p.repeatedBatch()).andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("3403"));
        } finally {
            org.springframework.test.util.ReflectionTestUtils.setField(reuseService, "newAssociationsEnabled", true);
        }
        verify(executor, times(2)).checkReuse(anyLong(), anyLong(), anyString(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), anyString());
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    void historicalRandomCodeWithSameDateAndTierIsNotACompetingSpecialCodeOwner() throws Exception {
        var p = pair("LEGACY_RANDOM");
        var legacy = group(p.session(), p.market(), "LEGACY_RANDOM_OWNER");
        long legacyIssue = legacy.at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='3404',workflow_status='CODE_IMPORTED',state='GENERATED',redemption_code='20F3747D' where id=?", legacyIssue);
        jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)", legacyIssue, 0, p.market(), "20F3747D");
        var before = jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", legacyIssue);
        create(p).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.issues[0].reusedFromIssueId").value(p.owner()));
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", legacyIssue)).isEqualTo(before);
        verify(executor, never()).create(any(), any(), any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    void multipleLocalConfigurationOwnersNeverChooseAnArbitraryOne() throws Exception {
        var p = pair("AMBIGUOUS");
        var third = group(p.session(), p.market(), "THIRD_AMBIGUOUS");
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='3404',workflow_status='CREATED' where id=?", third.at("/issues/0/id").asLong());
        create(p).andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REUSE_AMBIGUOUS_CONFIGURATION"));
        verifyNoInteractions(executor, standalone);
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
                 "remoteOptions":{"publishEnvironment":"test","flowTimes":5,"creationIntervalSeconds":5,"keyNumber":%d,"singleUserLimit":1,"singleKeyLimit":3000,"requireBindBankCard":false,"requireBindPhone":true,"checkUuid":true,"uuidRewardLimit":1,"checkLoginIp":true,"loginIpRewardLimit":1,"checkRegisterIp":true,"registerIpRewardLimit":1}}
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
