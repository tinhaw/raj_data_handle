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
class RedemptionRecoveryHttpTest {
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

    private JsonNode inspect(Pair p) throws Exception {
        return send(p.session(), "/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/recovery-check", "{}");
    }
    private org.springframework.test.web.servlet.ResultActions rebuild(Pair p, JsonNode view) throws Exception {
        return mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + p.alias() + "/rebuild")
                .session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                .content(mapper.writeValueAsString(java.util.Map.of("recoveryId",view.path("id").asLong(),
                        "rowVersion",view.path("rowVersion").asLong(),"confirmed",true))));
    }
    private void absent() {
        when(executor.checkRecovery(any(), anyString(), any(), anyBoolean())).thenAnswer(call -> {
            assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            return new UnifiedRedemptionRemoteExecutorClient.RecoveryCheck(call.getArgument(1), "ABSENT", java.time.Instant.now());
        });
    }
    private void created(String id) {
        when(executor.create(anyLong(), anyLong(), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenAnswer(call -> {
                    assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
                    return new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration(id, "group-"+id, "synthetic-receipt");
                });
        when(executor.checkReuse(anyLong(), anyLong(), eq(id), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck(id,true,java.util.List.of()));
    }

    @Test
    void failedReusePersistsMissingReasonAcrossReloadWithoutCreating() throws Exception {
        var p = pair("AUTO_MISSING"); absent();
        when(executor.checkReuse(anyLong(), anyLong(), eq("3403"), anyString(), any(), any(), any(), anyList(), any(), any(), any(), any()))
                .thenThrow(com.rajads.erp.shared.ApiException.conflict("REMOTE_REUSE_CHECK_REJECTED", "Empty remote read"));
        create(p).andExpect(status().isConflict());
        detail(p,p.repeatedBatch()).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.issues[0].recovery.status").value("MISSING"))
                .andExpect(jsonPath("$.data.issues[0].recovery.reason").isNotEmpty());
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void sharedImportedOwnerRebuildUsesRequestingTaskSnapshotPreservesInventoryAndInvalidatesOldPublication() throws Exception {
        var p = pair("SHARED_REBUILD"); create(p).andExpect(status().isOk());
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='CODE_IMPORTED',state='GENERATED',redemption_code='0905RAJ7DAYS0' where id=?",p.owner());
        jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)",p.owner(),0,p.market(),"0905RAJ7DAYS0");
        jdbc.update("update erp_compat_redemption_code_issues set bonus_max_amount=9 where id=?",p.alias());
        jdbc.update("update erp_compat_redemption_code_batches set remote_single_key_limit=123,published_at=CURRENT_TIMESTAMP,remote_publish_task_id='old-proof',status='COMPLETED' where id in (?,?)",p.originalBatch(),p.repeatedBatch());
        absent(); created("4901"); var view=inspect(p);
        assertThat(view.path("parameters").path("bonusMax").decimalValue()).isEqualByComparingTo("9");
        rebuild(p,view).andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("4901"))
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("CREATED"))
                .andExpect(jsonPath("$.data.batch.status").value("READY_TO_PUBLISH"));
        rebuild(p,view).andExpect(status().isOk());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_historical_codes where owner_issue_id=?",Integer.class,p.owner())).isEqualTo(1);
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?",Integer.class,p.owner())).isEqualTo(1);
        assertThat(jdbc.queryForObject("select reused_from_issue_id from erp_compat_redemption_code_issues where id=?",Long.class,p.alias())).isEqualTo(p.owner());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_code_batches where id in (?,?) and remote_publish_task_id is not null",Integer.class,p.originalBatch(),p.repeatedBatch())).isZero();
        verify(executor,times(1)).create(eq(p.account()),eq(p.alias()),anyString(),any(),any(),any(),anyList(),any(),argThat(v->v.compareTo(java.math.BigDecimal.valueOf(9))==0),argThat(o->o.singleKeyLimit()==123),eq("0905raj7days0"));
        verify(executor,never()).publish(any(),any(),any(),anyBoolean(),any(),anyBoolean());
    }

    @Test
    void receiptReadbackFailureRetriesOnlyRegistration() throws Exception {
        var p=pair("RECEIPT"); absent(); created("4902"); var view=inspect(p);
        when(executor.checkReuse(anyLong(),anyLong(),eq("4902"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),any()))
                .thenThrow(com.rajads.erp.shared.ApiException.conflict("READ_UNAVAILABLE","read failed"))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("4902",true,java.util.List.of()));
        rebuild(p,view).andExpect(status().isConflict());
        var resumed=inspect(p); assertThat(resumed.path("status").asText()).isEqualTo("RECEIPT_SAVED");
        rebuild(p,resumed).andExpect(status().isOk());
        verify(executor,times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void unknownCreateNeverReplaysEvenAfterRepeatedInspection() throws Exception {
        var p=pair("UNCERTAIN"); absent(); var view=inspect(p);
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any()))
                .thenThrow(new RuntimeException("synthetic timeout after request"));
        rebuild(p,view).andExpect(status().isConflict());
        var resumed=inspect(p); assertThat(resumed.path("status").asText()).isEqualTo("UNCONFIRMED");
        rebuild(p,resumed).andExpect(status().isConflict());
        verify(executor,times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void staleSnapshotOrChangedAbsencePreventsCreate() throws Exception {
        var p=pair("STALE_PARAMETERS"); absent(); var view=inspect(p);
        jdbc.update("update erp_compat_redemption_code_issues set bonus_max_amount=17,row_version=row_version+1 where id=?",p.alias());
        rebuild(p,view).andExpect(status().isConflict());
        var fresh=inspect(p);
        when(executor.checkRecovery(any(),anyString(),any(),anyBoolean())).thenReturn(
                new UnifiedRedemptionRemoteExecutorClient.RecoveryCheck("3403","PRESENT",java.time.Instant.now()));
        rebuild(p,fresh).andExpect(status().isConflict());
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void deniedProbePersistsUnavailableAndCannotBeRetriedAsCreate() throws Exception {
        var p=pair("DENIED");
        when(executor.checkRecovery(any(),anyString(),any(),anyBoolean()))
                .thenThrow(com.rajads.erp.shared.ApiException.conflict("REMOTE_RECOVERY_CHECK_REJECTED","403"));
        var view=inspect(p); assertThat(view.path("status").asText()).isEqualTo("CHECK_UNAVAILABLE");
        rebuild(p,view).andExpect(status().isConflict());
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void doubleClickAcrossRequestsReservesOneCreate() throws Exception {
        var p=pair("CONCURRENT"); absent(); created("4903"); var view=inspect(p);
        var entered=new java.util.concurrent.CountDownLatch(1); var release=new java.util.concurrent.CountDownLatch(1);
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any())).thenAnswer(call->{
            entered.countDown(); assertThat(release.await(10,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            return new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("4903","group-4903",null);
        });
        try(var pool=java.util.concurrent.Executors.newSingleThreadExecutor()) {
            var first=pool.submit(()->{ try{return rebuild(p,view).andReturn().getResponse().getStatus();}catch(Exception e){throw new RuntimeException(e);} });
            assertThat(entered.await(10,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            rebuild(p,view).andExpect(status().isConflict());
            jdbc.update("update erp_compat_redemption_recoveries set updated_at=? where id=?",java.sql.Timestamp.from(java.time.Instant.now().minusSeconds(121)),view.path("id").asLong());
            var stale=inspect(p); assertThat(stale.path("status").asText()).isEqualTo("UNCONFIRMED");
            rebuild(p,stale).andExpect(status().isConflict()); release.countDown();
            assertThat(first.get(10,java.util.concurrent.TimeUnit.SECONDS)).isEqualTo(200);
        } finally { release.countDown(); }
        verify(executor,times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void randomMultiCodeGenerationsRetainOldStockAndUseNewQuantity() throws Exception {
        var session=login(); long market=market(session,"RECOVERY_RANDOM"); long account=account(session,market,"random-recovery");
        var original=group(session,market,"RANDOM_OWNER",2); long owner=original.at("/issues/0/id").asLong();
        long batch=original.at("/batch/id").asLong();
        var p=new Pair(session,market,account,original,original);
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='6700',remote_group_key='old-random-group',workflow_status='CODE_IMPORTED',state='GENERATED',redemption_code='old-a' where id=?",owner);
        jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)",owner,0,market,"old-a");
        jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)",owner,1,market,"old-b");
        jdbc.update("update erp_compat_redemption_code_batches set remote_key_number=3 where id=?",batch);
        absent(); created("6701"); var view=inspect(p);
        rebuild(p,view).andExpect(status().isOk());
        new org.springframework.transaction.support.TransactionTemplate(tm).executeWithoutResult(tx->{
            var issue=issues.findById(owner).orElseThrow();
            assertThat(storage.store(issue,batches.findById(batch).orElseThrow(),java.util.List.of("new-a","new-b","new-c"))).isEqualTo(3);
            issue.setWorkflowStatus("CODE_IMPORTED"); issue.setState("GENERATED"); issues.saveAndFlush(issue);
        });
        assertThat(jdbc.queryForList("select code from erp_compat_redemption_historical_codes where owner_issue_id=? order by code_index",String.class,owner)).containsExactly("old-a","old-b");
        assertThat(jdbc.queryForList("select code from erp_compat_redemption_issue_codes where issue_id=? order by code_index",String.class,owner)).containsExactly("new-a","new-b","new-c");
        verify(executor,times(1)).create(eq(account),eq(owner),anyString(),any(),any(),any(),anyList(),any(),any(),argThat(o->o.keyNumber()==3),isNull());
    }

    @Test
    void sharedScopeChangedDuringProbeStopsBeforeReservingRemoteWrite() throws Exception {
        var p=pair("SCOPE_CHANGED"); absent(); var view=inspect(p);
        var third=group(p.session(),p.market(),"SCOPE_THIRD"); long thirdId=third.at("/issues/0/id").asLong();
        when(executor.checkRecovery(any(),anyString(),any(),anyBoolean())).thenAnswer(call->{
            jdbc.update("update erp_compat_redemption_code_issues set reused_from_issue_id=?,workflow_status='CREATED' where id=?",p.owner(),thirdId);
            return new UnifiedRedemptionRemoteExecutorClient.RecoveryCheck("3403","ABSENT",java.time.Instant.now());
        });
        rebuild(p,view).andExpect(status().isConflict());
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test
    void previouslyKnownMissingOwnerAttachesDurableRecoveryToAnotherRequestingTask() throws Exception {
        var p=pair("KNOWN_MISSING"); absent(); inspect(p);
        var third=group(p.session(),p.market(),"KNOWN_THIRD"); long thirdId=third.at("/issues/0/id").asLong();
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+thirdId+"/reuse")
                .session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{\"rowVersion\":"+jdbc.queryForObject("select row_version from erp_compat_redemption_code_issues where id=?",Long.class,thirdId)+"}")).andExpect(status().isConflict());
        detail(p,third.at("/batch/id").asLong()).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.issues[0].recovery.status").value("MISSING"));
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        created("4906"); rebuild(p,inspect(p)).andExpect(status().isOk());
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+thirdId+"/reuse")
                .session(p.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{\"rowVersion\":"+jdbc.queryForObject("select row_version from erp_compat_redemption_code_issues where id=?",Long.class,thirdId)+"}")).andExpect(status().isOk());
        assertThat(jdbc.queryForObject("select pending_recovery_id from erp_compat_redemption_code_issues where id=?",Long.class,thirdId)).isNull();
        assertThat(jdbc.queryForObject("select reused_from_issue_id from erp_compat_redemption_code_issues where id=?",Long.class,thirdId)).isEqualTo(p.owner());
    }

    @Test
    void oldDownloadReturningAfterRebuildCannotImportOldCodesIntoNewGeneration() throws Exception {
        var p=pair("DOWNLOAD_RACE"); create(p).andExpect(status().isOk()); absent(); created("4905");
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='PUBLISHED' where id=?",p.owner());
        jdbc.update("update erp_compat_redemption_code_batches set status='PUBLISHED',remote_publish_task_id='old-publish' where id=?",p.repeatedBatch());
        when(executor.verifyPublication(eq(p.account()),eq(p.repeatedBatch()),eq("old-publish"),eq("test"),anyList()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublicationVerification("old-publish",3,"COMPLETED",false,
                        java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification("3403","MATCHED")),java.time.Instant.now().toString(),null));
        var entered=new java.util.concurrent.CountDownLatch(1); var release=new java.util.concurrent.CountDownLatch(1);
        when(executor.download(anyLong(),eq(p.alias()),eq("3403"),anyString(),eq(1))).thenAnswer(call->{
            entered.countDown(); assertThat(release.await(10,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            return new UnifiedRedemptionRemoteExecutorClient.DownloadedCodes(java.util.List.of("old-download"),"group-3403");
        });
        try(var pool=java.util.concurrent.Executors.newSingleThreadExecutor()) {
            var first=pool.submit(()->{ try{return mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+p.alias()+"/remote-download")
                    .session(p.session()).with(csrf())).andReturn().getResponse().getStatus();}catch(Exception e){throw new RuntimeException(e);} });
            assertThat(entered.await(10,java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            var view=inspect(p); rebuild(p,view).andExpect(status().isOk()); release.countDown();
            assertThat(first.get(10,java.util.concurrent.TimeUnit.SECONDS)).isEqualTo(409);
        } finally { release.countDown(); }
        assertThat(jdbc.queryForObject("select state from erp_compat_redemption_code_issues where id=?",String.class,p.owner())).isEqualTo("PENDING");
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?",Integer.class,p.owner())).isZero();
        assertThat(jdbc.queryForObject("select remote_error from erp_compat_redemption_code_issues where id=?",String.class,p.alias())).isNull();
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
