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
class RedemptionPolicyUpdateHttpTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired JdbcTemplate jdbc;
    @Autowired RedemptionReuseService reuseService;
    @Autowired RedemptionRecoveryService recovery;
    @Autowired RedemptionCodeStorage storage;
    @Autowired RedemptionCodeIssueRepository issues;
    @Autowired RedemptionCodeBatchRepository batches;
    @Autowired org.springframework.transaction.PlatformTransactionManager tm;
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

    private java.util.concurrent.atomic.AtomicBoolean remoteUpdated;
    private Pair prepared(String name) throws Exception {
        var p=pair("POLICY_"+name); remoteUpdated=new java.util.concurrent.atomic.AtomicBoolean(false);
        jdbc.update("update erp_compat_redemption_code_issues set reused_from_issue_id=?,workflow_status='CREATED',bonus_max_amount=7 where id=?",p.owner(),p.alias());
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='CODE_IMPORTED',state='GENERATED',redemption_code='0905raj7days0' where id=?",p.owner());
        jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)",p.owner(),0,p.market(),"0905raj7days0");
        when(executor.checkReuse(anyLong(),anyLong(),eq("3403"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any())).thenAnswer(call->{
            assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            return response(remoteUpdated.get());
        });
        when(executor.updateReward(any(),eq("3403"))).thenAnswer(call->{
            assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            RedemptionRecoveryService.Snapshot snapshot=call.getArgument(0);
            assertThat(snapshot.bonusMax()).isEqualByComparingTo("7"); remoteUpdated.set(true); return response(true);
        });
        return p;
    }
    private UnifiedRedemptionRemoteExecutorClient.ReuseCheck response(boolean matched) {
        return new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403",matched,matched?java.util.List.of():java.util.List.of("reward_max"),"group-3403",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(matched?7:3));
    }
    private JsonNode check(Pair p) throws Exception {
        return send(p.session(),"/api/v1/redemption-campaigns/code-tasks/"+p.alias()+"/reward-policy/check","{}");
    }
    private org.springframework.test.web.servlet.ResultActions apply(Pair p,JsonNode view) throws Exception {
        return mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+p.alias()+"/reward-policy/apply").session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                .content(mapper.writeValueAsString(java.util.Map.of("policyUpdateId",view.path("id").asLong(),"rowVersion",view.path("rowVersion").asLong(),"confirmed",true))));
    }

    @Test
    void newTaskWithImportedSameCodeWaitsForRewardConfirmationAndCannotPublishDownloadOrExport() throws Exception {
        var p=prepared("CREATION_CONFIRM");
        jdbc.update("update erp_compat_redemption_code_issues set reused_from_issue_id=null,workflow_status='PENDING_CREATION' where id=?",p.alias());
        create(p).andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("CREATING"))
                .andExpect(jsonPath("$.data.batch.importedCount").value(0))
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("REWARD_CONFIRM_REQUIRED"))
                .andExpect(jsonPath("$.data.issues[0].state").value("PENDING"))
                .andExpect(jsonPath("$.data.issues[0].redemptionCode").doesNotExist());
        var view=check(p);
        assertThat(view.path("previousMax").decimalValue()).isEqualByComparingTo("3");
        assertThat(view.at("/parameters/bonusMax").decimalValue()).isEqualByComparingTo("7");
        // A refresh, cancellation, or retry cannot inherit the owner's successful import.
        create(p).andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].workflowStatus").value("REWARD_CONFIRM_REQUIRED"));
        detail(p,p.repeatedBatch()).andExpect(jsonPath("$.data.batch.status").value("CREATING"));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+p.alias()+"/remote-download").session(p.session()).with(csrf()))
                .andExpect(status().isConflict());
        mvc.perform(post("/api/v1/redemption-campaigns/batches/"+p.repeatedBatch()+"/remote-publish").session(p.session()).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content("{\"mode\":\"IMMEDIATE\",\"rowVersion\":0}"))
                .andExpect(status().isConflict());
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/v1/redemption-campaigns/batches/"+p.repeatedBatch()+"/export").session(p.session()))
                .andExpect(status().isConflict());
        verify(executor,never()).updateReward(any(),any());
        verify(executor,never()).download(any(),any(),any(),any(),anyInt());
        verify(executor,never()).publish(any(),any(),any(),anyBoolean(),any(),anyBoolean());
        apply(p,check(p)).andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("READY_TO_PUBLISH"))
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("CREATED"));
        assertThat(remoteUpdated.get()).isTrue();
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?",Integer.class,p.owner())).isEqualTo(1);
        verify(executor,times(1)).updateReward(any(),eq("3403"));
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void absentActualAmountsCannotInheritCompletedOwner() throws Exception {
        var p=prepared("NO_ACTUAL");
        jdbc.update("update erp_compat_redemption_code_issues set reused_from_issue_id=null,workflow_status='PENDING_CREATION' where id=?",p.alias());
        when(executor.checkReuse(anyLong(),anyLong(),eq("3403"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403",true,java.util.List.of()));
        create(p).andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].workflowStatus").value("REWARD_CHECK_REQUIRED"))
                .andExpect(jsonPath("$.data.batch.status").value("CREATING"));
        verify(executor,never()).updateReward(any(),any());
    }

    @Test
    void freshlyCreatedReceiptSurvivesFailedRewardReadAndRetryDoesNotCreateAgain() throws Exception {
        var p=pair("NEW_READBACK");
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id=null,remote_reference_id=null,workflow_status='FAILED' where id=?",p.owner());
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("4909","group-4909",null));
        when(executor.checkReuse(anyLong(),anyLong(),eq("4909"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any()))
                .thenThrow(com.rajads.erp.shared.ApiException.conflict("READ_UNAVAILABLE","synthetic read failure"));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/remote-create").session(p.session()).with(csrf())).andExpect(status().isConflict());
        detail(p,p.repeatedBatch()).andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("4909"))
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("REWARD_CHECK_REQUIRED"));
        when(executor.checkReuse(anyLong(),anyLong(),eq("4909"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("4909",true,java.util.List.of(),"group-4909",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(3)));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/remote-create").session(p.session()).with(csrf())).andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("READY_TO_PUBLISH"));
        verify(executor,times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void changedActualRewardsAfterConfirmationRequireNewConsent() throws Exception {
        var p=prepared("CHANGED_ACTUAL");var view=check(p);
        when(executor.checkReuse(anyLong(),anyLong(),eq("3403"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403",false,java.util.List.of("reward_max"),"group-3403",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(4)));
        apply(p,view).andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("POLICY_STATE_CHANGED"));
        assertThat(check(p).path("previousMax").decimalValue()).isEqualByComparingTo("4");
        verify(executor,never()).updateReward(any(),any());
    }
    @Test
    void checkingActualRewardsNeverMutatesRemoteOrInventory() throws Exception {
        var p=prepared("READ_ONLY");var before=jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?",p.owner());
        var view=check(p);assertThat(view.path("status").asText()).isEqualTo("CHECKED");
        assertThat(view.path("previousMax").decimalValue()).isEqualByComparingTo("3");
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?",p.owner())).isEqualTo(before);
        verify(executor,never()).updateReward(any(),any());
    }
    @Test
    void rewardUpdateKeepsSharedIdentityInventoryAndOriginalTaskPolicyAndRequiresNewPublication() throws Exception {
        var p=prepared("SHARED");jdbc.update("update erp_compat_redemption_code_batches set remote_publish_task_id='old',published_at=CURRENT_TIMESTAMP,status='COMPLETED' where id in (?,?)",p.originalBatch(),p.repeatedBatch());
        var view=check(p);apply(p,view).andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("3403"))
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("CREATED"))
                .andExpect(jsonPath("$.data.batch.status").value("READY_TO_PUBLISH"));
        apply(p,view).andExpect(status().isOk());assertThat(check(p).path("status").asText()).isEqualTo("MATCHED");
        assertThat(jdbc.queryForObject("select bonus_max_amount from erp_compat_redemption_code_issues where id=?",java.math.BigDecimal.class,p.owner())).isEqualByComparingTo("3");
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?",Integer.class,p.owner())).isEqualTo(1);
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_code_batches where id in (?,?) and remote_publish_task_id is not null",Integer.class,p.originalBatch(),p.repeatedBatch())).isZero();
        verify(executor,times(1)).updateReward(any(),eq("3403"));verify(executor,never()).publish(any(),any(),any(),anyBoolean(),any(),anyBoolean());
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }
    @Test
    void lostUpdateResponseResumesOnlyAfterReadbackWithoutRepeatingPut() throws Exception {
        var p=prepared("LOST_RESPONSE");var view=check(p);
        when(executor.updateReward(any(),any())).thenAnswer(call->{remoteUpdated.set(true);throw new RuntimeException("synthetic response lost");});
        apply(p,view).andExpect(status().isConflict());var resumed=check(p);assertThat(resumed.path("status").asText()).isEqualTo("UNCONFIRMED");
        apply(p,resumed).andExpect(status().isOk());verify(executor,times(1)).updateReward(any(),any());
    }
    @Test
    void unknownWriteThatHasNotReadBackCannotBeRetriedAsAnotherPut() throws Exception {
        var p=prepared("UNCERTAIN");var view=check(p);when(executor.updateReward(any(),any())).thenThrow(new RuntimeException("timeout"));
        apply(p,view).andExpect(status().isConflict());apply(p,check(p)).andExpect(status().isConflict());
        verify(executor,times(1)).updateReward(any(),any());
    }
    @Test
    void sharedUnknownUpdateNeverReturnsAnotherTasksConfirmationAsThisTasksPlan() throws Exception {
        var p=prepared("SHARED_UNKNOWN");var view=check(p);
        when(executor.updateReward(any(),any())).thenThrow(new RuntimeException("synthetic timeout"));
        apply(p,view).andExpect(status().isConflict());
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+p.owner()+"/reward-policy/check").session(p.session()).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("POLICY_SHARED_UPDATE_PENDING"));
        verify(executor,times(1)).updateReward(any(),any());
    }
    @Test
    void missingUpdateCapabilityFailsBeforeReservationAndCanBeAuthorizedLater() throws Exception {
        var p=prepared("CAPABILITY");
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='REWARD_CONFIRM_REQUIRED' where id=?",p.alias());
        var view=check(p);
        doThrow(com.rajads.erp.shared.ApiException.conflict("REWARD_UPDATE_NOT_AUTHORIZED","not authorized")).when(executor).requireRewardUpdateCapability(anyLong(),anyLong());
        apply(p,view).andExpect(status().isConflict());
        assertThat(jdbc.queryForObject("select remote_error from erp_compat_redemption_code_issues where id=?",String.class,p.owner())).isNull();
        verify(executor,never()).updateReward(any(),any());
        detail(p,p.repeatedBatch()).andExpect(jsonPath("$.data.issues[0].workflowStatus").value("REWARD_CONFIRM_REQUIRED"))
                .andExpect(jsonPath("$.data.batch.importedCount").value(0));
        doNothing().when(executor).requireRewardUpdateCapability(anyLong(),anyLong());apply(p,check(p)).andExpect(status().isOk());
    }

    @Test
    void creationReturningValidIdWithWrongActualRewardStillRequiresExplicitConfirmation() throws Exception {
        var p=pair("NEW_WRONG_REWARD");
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id=null,remote_reference_id=null,workflow_status='FAILED' where id=?",p.owner());
        jdbc.update("update erp_compat_redemption_code_issues set bonus_max_amount=7 where id=?",p.alias());
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("4910","group-4910",null));
        when(executor.checkReuse(anyLong(),anyLong(),eq("4910"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("4910",false,java.util.List.of("reward_max"),"group-4910",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(3)));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/remote-create").session(p.session()).with(csrf())).andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("4910"))
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("REWARD_CONFIRM_REQUIRED"))
                .andExpect(jsonPath("$.data.batch.status").value("CREATING"));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/remote-create").session(p.session()).with(csrf())).andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].workflowStatus").value("REWARD_CONFIRM_REQUIRED"));
        verify(executor,times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        verify(executor,never()).updateReward(any(),any());
    }
    @Test
    void nonRewardMismatchCannotBeOverwritten() throws Exception {
        var p=prepared("OTHER_POLICY");when(executor.checkReuse(anyLong(),anyLong(),anyString(),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("3403",false,java.util.List.of("single_key_limit"),"group-3403",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(3)));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+p.alias()+"/reward-policy/check").session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isConflict());verify(executor,never()).updateReward(any(),any());
    }
    @Test
    void concurrentConfirmationReservesOneUpdate() throws Exception {
        var p=prepared("CONCURRENT");var view=check(p);var entered=new java.util.concurrent.CountDownLatch(1);var release=new java.util.concurrent.CountDownLatch(1);
        when(executor.updateReward(any(),any())).thenAnswer(call->{entered.countDown();assertThat(release.await(10,java.util.concurrent.TimeUnit.SECONDS)).isTrue();remoteUpdated.set(true);return response(true);});
        try(var pool=java.util.concurrent.Executors.newSingleThreadExecutor()) {
            var first=pool.submit(()->{try{return apply(p,view).andReturn().getResponse().getStatus();}catch(Exception e){throw new RuntimeException(e);}});
            assertThat(entered.await(10,java.util.concurrent.TimeUnit.SECONDS)).isTrue();apply(p,view).andExpect(status().isConflict());release.countDown();
            assertThat(first.get(10,java.util.concurrent.TimeUnit.SECONDS)).isEqualTo(200);
        }finally{release.countDown();}
        verify(executor,times(1)).updateReward(any(),any());
    }
    @Test
    void readbackFailureAfterReceiptOnlyResumesRegistration() throws Exception {
        var p=prepared("REGISTER");var view=check(p);var fail=new java.util.concurrent.atomic.AtomicBoolean(true);
        when(executor.checkReuse(anyLong(),anyLong(),anyString(),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any())).thenAnswer(call->{
            if(remoteUpdated.get()&&fail.getAndSet(false)) throw com.rajads.erp.shared.ApiException.conflict("READ_UNAVAILABLE","read temporarily unavailable");return response(remoteUpdated.get());});
        apply(p,view).andExpect(status().isConflict());var resumed=check(p);assertThat(resumed.path("status").asText()).isEqualTo("UPDATED");apply(p,resumed).andExpect(status().isOk());
        verify(executor,times(1)).updateReward(any(),any());
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
