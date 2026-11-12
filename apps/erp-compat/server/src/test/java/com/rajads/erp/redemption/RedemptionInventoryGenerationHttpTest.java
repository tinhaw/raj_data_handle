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
class RedemptionInventoryGenerationHttpTest {
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



    private record Fixture(MockHttpSession session, long market, long account, long oldId, long newId, long batch) {}
    private Fixture fixture(String name) throws Exception {
        var session=login(); long market=market(session,"INV_"+name); long account=account(session,market,"inv-"+name.toLowerCase());
        var old=group(session,market,"OLD_"+name); var fresh=group(session,market,"NEW_"+name);
        long oldId=old.at("/issues/0/id").asLong(), newId=fresh.at("/issues/0/id").asLong(), batch=fresh.at("/batch/id").asLong();
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='1000',remote_group_key='group-1000',workflow_status='PUBLISHED' where id=?",oldId);
        jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='2000',remote_group_key='group-2000',workflow_status='PUBLISHED' where id=?",newId);
        jdbc.update("update erp_compat_redemption_code_batches set status='PUBLISHED',remote_publish_task_id='3000' where id=?",batch);
        new org.springframework.transaction.support.TransactionTemplate(tm).executeWithoutResult(s->{
            var owner=issues.findById(oldId).orElseThrow(); storage.store(owner,batches.findById(owner.getBatchId()).orElseThrow(),java.util.List.of("0905RAJ7DAYS0"));
            owner.setWorkflowStatus("CODE_IMPORTED");owner.setState("GENERATED");
        });
        when(executor.verifyPublication(eq(account),eq(batch),eq("3000"),eq("test"),anyList()))
            .thenReturn(new UnifiedRedemptionRemoteExecutorClient.PublicationVerification("3000",4,"COMPLETED",false,
                java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.ConfigurationVerification("2000","MATCHED")),java.time.Instant.now().toString(),null));
        when(executor.download(eq(account),eq(newId),eq("2000"),eq("group-2000"),eq(1)))
            .thenReturn(new UnifiedRedemptionRemoteExecutorClient.DownloadedCodes(java.util.List.of("0905raj7days0"),"group-2000"));
        return new Fixture(session,market,account,oldId,newId,batch);
    }
    private org.springframework.test.web.servlet.ResultActions download(Fixture f) throws Exception {
        return mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+f.newId()+"/remote-download").session(f.session()).with(csrf()));
    }
    private void store(Fixture f, boolean downloaded) {
        new org.springframework.transaction.support.TransactionTemplate(tm).executeWithoutResult(s->{
            var owner=issues.findById(f.newId()).orElseThrow();var batch=batches.findById(f.batch()).orElseThrow();
            if(downloaded)storage.storeDownloaded(owner,batch,java.util.List.of("0905raj7days0"));
            else storage.store(owner,batch,java.util.List.of("0905raj7days0"));
        });
    }
    @Test void verifiedDownloadKeepsBothGenerationsAndRetriesWithoutDownloadingAgain() throws Exception {
        var f=fixture("DOWNLOAD");
        download(f).andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.status").value("COMPLETED"));
        download(f).andExpect(status().isOk());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where remote_market_id=?",Integer.class,f.market())).isEqualTo(2);
        assertThat(jdbc.queryForObject("select code from erp_compat_redemption_issue_codes where issue_id=?",String.class,f.oldId())).isEqualTo("0905RAJ7DAYS0");
        assertThat(jdbc.queryForMap("select inventory_configuration_id,redemption_code from erp_compat_redemption_code_issues where id=?",f.newId()))
            .containsEntry("inventory_configuration_id","2000").containsEntry("redemption_code","0905raj7days0");
        verify(executor,times(1)).download(eq(f.account()),eq(f.newId()),eq("2000"),eq("group-2000"),eq(1));
        byte[] workbook=mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/api/v1/redemption-campaigns/batches/"+f.batch()+"/export").session(f.session()))
            .andExpect(status().isOk()).andReturn().getResponse().getContentAsByteArray();
        assertThat(workbook.length).isGreaterThan(1000);
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        verify(executor,never()).publish(any(),any(),any(),anyBoolean(),any(),anyBoolean());
    }
    @Test void historicalGenerationRemainsAndDoesNotBlockVerifiedNewConfiguration() throws Exception {
        var f=fixture("HISTORY");
        jdbc.update("insert into erp_compat_redemption_recoveries(owner_issue_id,requested_issue_id,remote_market_id,key_number,account_id,old_configuration_id,status,snapshot_json,history_json,created_at,updated_at) values(?,?,?,1,?,'900','PRESENT','{}','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",f.oldId(),f.oldId(),f.market(),f.account());
        long recovery=jdbc.queryForObject("select id from erp_compat_redemption_recoveries where owner_issue_id=?",Long.class,f.oldId());
        jdbc.update("insert into erp_compat_redemption_historical_codes(recovery_id,owner_issue_id,remote_market_id,configuration_id,code_index,code) values(?,?,?,'900',0,'0905RAJ7DAYS0')",recovery,f.oldId(),f.market());
        download(f).andExpect(status().isOk());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_historical_codes where recovery_id=?",Integer.class,recovery)).isEqualTo(1);
    }
    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings={"manual","ordinary","unknown","deletion","reward","wrong_code"})
    void unverifiedOrUnrelatedCollisionsAndExistingSafetyHoldsStillBlock(String mode) throws Exception {
        var f=fixture("BLOCK_"+mode.toUpperCase());
        switch(mode){
            case "ordinary" -> jdbc.update("update erp_compat_redemption_code_batches set redemption_type='AGENT' where id=?",f.batch());
            case "unknown" -> jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id=null where id=?",f.newId());
            case "deletion" -> jdbc.update("update erp_compat_redemption_code_issues set remote_deletion_state='DELETED' where id=?",f.newId());
            case "reward" -> jdbc.update("update erp_compat_redemption_code_issues set workflow_status='REWARD_CONFIRM_REQUIRED' where id=?",f.newId());
            case "wrong_code" -> jdbc.update("update erp_compat_redemption_code_issues set min_deposit_amount=200 where id=?",f.newId());
        }
        assertThatThrownBy(()->store(f,!mode.equals("manual"))).isInstanceOf(com.rajads.erp.shared.ApiException.class);
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?",Integer.class,f.newId())).isZero();
        assertThat(jdbc.queryForObject("select code from erp_compat_redemption_issue_codes where issue_id=?",String.class,f.oldId())).isEqualTo("0905RAJ7DAYS0");
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
