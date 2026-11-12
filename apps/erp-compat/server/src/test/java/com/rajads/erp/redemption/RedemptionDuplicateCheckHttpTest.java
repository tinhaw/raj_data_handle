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
class RedemptionDuplicateCheckHttpTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired JdbcTemplate jdbc;

    @MockBean RemoteGiftCodeBackendClient standalone;
    @MockBean RemoteOperationGate gate;
    @MockBean UnifiedRedemptionRemoteExecutorClient executor;



    private JsonNode setup(String suffix) throws Exception {
        var session = login();
        long market = market(session, "DUP_" + suffix);
        account(session, market, "duplicate-" + suffix.toLowerCase());
        return group(session, market, "DUP_OWNER_" + suffix);
    }
    private String draft(long market, boolean remote) {
        return "{\"markets\":[{\"marketId\":" + market + ",\"redemptionType\":\"SEVEN_DAY_DEPOSIT\",\"from\":\"2026-09-05\",\"to\":\"2026-09-05\",\"deposits\":[0]}],\"checkRemote\":" + remote + "}";
    }
    private long marketOf(long issue) { return jdbc.queryForObject("select remote_market_id from erp_compat_redemption_code_issues where id=?", Long.class, issue); }
    private void registered(long issue) { jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='3403',workflow_status='CREATED' where id=?", issue); }

    @Test void resumeAggregatesAllTaskMarketsAndOneReviewAuthorizesEachUnchangedConflict() throws Exception {
        var oldA = setup("RESUME_A"); var oldB = setup("RESUME_B");
        long ownerA = oldA.at("/issues/0/id").asLong(), ownerB = oldB.at("/issues/0/id").asLong();
        registered(ownerA); registered(ownerB);
        var a = group(login(), marketOf(ownerA), "RESUME_NEW_A");
        var b = group(login(), marketOf(ownerB), "RESUME_NEW_B");
        long batchA = a.at("/batch/id").asLong(), batchB = b.at("/batch/id").asLong();
        long targetA = a.at("/issues/0/id").asLong(), targetB = b.at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_batches set task_id=? where id=?", a.at("/batch/taskId").asLong(), batchB);
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='FAILED',remote_error='本地已有同码，未提交创建' where id=?", targetB);
        var preview = send(login(), "/api/v1/redemption-campaigns/batches/"+batchA+"/creation-duplicate-check", "{}");
        assertThat(preview.path("checkedCodes").asInt()).isEqualTo(2);
        assertThat(preview.path("conflicts").size()).isEqualTo(2);
        assertThat(preview.path("remoteChecked").asBoolean()).isFalse();
        verifyNoInteractions(executor, standalone);
        var fingerprints = new java.util.HashMap<String, String>();
        preview.path("conflicts").forEach(c -> fingerprints.put(c.path("issueId").asText(), c.path("reviewFingerprint").asText()));
        assertThat(fingerprints.keySet()).containsExactlyInAnyOrder(Long.toString(ownerA), Long.toString(ownerB));
        String review = mapper.writeValueAsString(java.util.Map.of("confirmed", true, "fingerprints", fingerprints));
        mvc.perform(post("/api/v1/redemption-campaigns/batches/"+batchA+"/creation-duplicate-review")
                .session(login()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(review)).andExpect(status().isOk());
        assertThat(send(login(), "/api/v1/redemption-campaigns/batches/"+batchB+"/creation-duplicate-check", "{}").path("reviewConfirmed").asBoolean()).isTrue();
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("9801","new-group",null));
        when(executor.checkReuse(anyLong(),anyLong(),eq("9801"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),anyString()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("9801",true,java.util.List.of(),"new-group",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(3)));
        for (long target : new long[]{targetA, targetB}) {
            mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+target+"/remote-create?retryFailed=true")
                    .session(login()).with(csrf()))
                    .andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("9801"));
        }
        verify(executor, times(2)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        var after = send(login(), "/api/v1/redemption-campaigns/batches/"+batchB+"/creation-duplicate-check", "{}");
        assertThat(after.path("checkedCodes").asInt()).isZero();
        assertThat(after.path("conflicts").isEmpty()).isTrue();
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_code_issues where id in (?,?) and remote_configuration_id='3403'", Integer.class, ownerA, ownerB)).isEqualTo(2);
    }

    @Test void resumePreviewDoesNotIncludeUnknownReceiptsOrPerformRemoteOperations() throws Exception {
        var old = setup("RESUME_UNKNOWN"); long owner = old.at("/issues/0/id").asLong(); registered(owner);
        var target = group(login(), marketOf(owner), "RESUME_UNKNOWN_NEW");
        long id = target.at("/issues/0/id").asLong(), batch = target.at("/batch/id").asLong();
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='FAILED',remote_error=? where id=?", RemoteConfigurationIds.UNCONFIRMED_PREFIX, id);
        var result = send(login(), "/api/v1/redemption-campaigns/batches/"+batch+"/creation-duplicate-check", "{}");
        assertThat(result.path("checkedCodes").asInt()).isZero();
        assertThat(result.path("conflicts").isEmpty()).isTrue();
        verifyNoInteractions(executor, standalone);
    }

    @Test void groupCreationSavesReviewAtomicallyAndNewSessionContinuesDespiteIncidentalProgress() throws Exception {
        var old = setup("DURABLE"); long owner = old.at("/issues/0/id").asLong(); registered(owner);
        long market = marketOf(owner);
        var preview = send(login(), "/api/v1/redemption-campaigns/groups/duplicate-check", draft(market, false));
        var input = (com.fasterxml.jackson.databind.node.ObjectNode) mapper.readTree(groupRequest(market, "DURABLE_NEW", 1));
        input.set("duplicateReview", mapper.valueToTree(java.util.Map.of("confirmed", true, "fingerprints",
                java.util.Map.of(Long.toString(owner), preview.at("/conflicts/0/reviewFingerprint").asText(), "999999", "not-reviewed"))));
        var created = send(login(), "/api/v1/redemption-campaigns/groups", mapper.writeValueAsString(input));
        long target = created.at("/issues/0/id").asLong(), batch = created.at("/batch/id").asLong();
        String saved = jdbc.queryForObject("select after_json from erp_compat_audit_logs where action='REDEMPTION_TASK_DUPLICATES_CONFIRMED' and entity_id=? order by id desc limit 1", String.class, created.at("/batch/taskId").asText());
        assertThat(mapper.readTree(saved).path("fingerprints").size()).isEqualTo(1);
        assertThat(saved).doesNotContain("999999");
        jdbc.update("update erp_compat_redemption_code_issues set row_version=row_version+1,workflow_status='CODE_IMPORTED' where id=?", owner);
        assertThat(send(login(), "/api/v1/redemption-campaigns/batches/"+batch+"/creation-duplicate-check", "{}").path("reviewConfirmed").asBoolean()).isTrue();
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("9802","durable-group",null));
        when(executor.checkReuse(anyLong(),eq(target),eq("9802"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),anyString()))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("9802",true,java.util.List.of(),"durable-group",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(3)));
        // New login, no browser memory, and no explicit review payload.
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+target+"/remote-create").session(login()).with(csrf()))
                .andExpect(status().isOk());
        verify(executor, times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        var other = group(login(), market, "DURABLE_OTHER");
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+other.at("/issues/0/id").asLong()+"/remote-create").session(login()).with(csrf()))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("LOCAL_REDEMPTION_DUPLICATE"));
        verify(executor, times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }

    @Test void staleInitialApprovalRollsBackButSavedTaskAcknowledgementSurvivesHistoricalChanges() throws Exception {
        var old = setup("DURABLE_CHANGE"); long owner = old.at("/issues/0/id").asLong(); registered(owner);
        long market = marketOf(owner);
        var preview = send(login(), "/api/v1/redemption-campaigns/groups/duplicate-check", draft(market, false));
        var input = (com.fasterxml.jackson.databind.node.ObjectNode) mapper.readTree(groupRequest(market, "DURABLE_REJECT", 1));
        input.set("duplicateReview", mapper.valueToTree(java.util.Map.of("confirmed", true, "fingerprints", java.util.Map.of(Long.toString(owner), "stale"))));
        Integer tasksBefore = jdbc.queryForObject("select count(*) from erp_compat_redemption_code_tasks", Integer.class);
        mvc.perform(post("/api/v1/redemption-campaigns/groups").session(login()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(input)))
                .andExpect(status().isConflict());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_campaigns where code='DURABLE_REJECT'", Integer.class)).isZero();
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_code_tasks", Integer.class)).isEqualTo(tasksBefore);
        input.put("code", "DURABLE_ACCEPT");
        input.set("duplicateReview", mapper.valueToTree(java.util.Map.of("confirmed", true, "fingerprints", java.util.Map.of(Long.toString(owner), preview.at("/conflicts/0/reviewFingerprint").asText()))));
        var created = send(login(), "/api/v1/redemption-campaigns/groups", mapper.writeValueAsString(input));
        jdbc.update("update erp_compat_redemption_code_issues set bonus_max_amount=7 where id=?", owner);
        long batch = created.at("/batch/id").asLong(), task = created.at("/batch/taskId").asLong();
        assertThat(send(login(), "/api/v1/redemption-campaigns/batches/"+batch+"/creation-duplicate-check", "{}").path("reviewConfirmed").asBoolean()).isTrue();
        // A repeat confirmation is idempotent, even with the old browser fingerprint.
        send(login(), "/api/v1/redemption-campaigns/batches/"+batch+"/creation-duplicate-review", mapper.writeValueAsString(input.path("duplicateReview")));
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_audit_logs where action='REDEMPTION_TASK_DUPLICATES_CONFIRMED' and entity_id=?", Integer.class, Long.toString(task))).isEqualTo(1);
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any()))
                .thenThrow(com.rajads.erp.shared.ApiException.badRequest("REMOTE_CREATE_FAILED", "指定兑换码串已被使用，请更换~"));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+created.at("/issues/0/id").asLong()+"/remote-create").session(login()).with(csrf())
                .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(input.path("duplicateReview"))))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("REMOTE_CREATE_FAILED"));
        // Confirmation cannot turn a remote rejection into success or silently choose reuse/update/delete.
        verify(executor, times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        verifyNoMoreInteractions(executor);
        verifyNoInteractions(standalone);
        assertThat(send(login(), "/api/v1/redemption-campaigns/batches/"+batch+"/creation-duplicate-check", "{}").path("reviewConfirmed").asBoolean()).isTrue();
    }

    @Test void localPreviewFindsUndownloadedConfigAndDoesNotReadOrWriteRemote() throws Exception {
        var owner=setup("PREVIEW"); long issue=owner.at("/issues/0/id").asLong(); registered(issue);
        var before=jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?",issue);
        var result=send(login(),"/api/v1/redemption-campaigns/groups/duplicate-check",draft(marketOf(issue),false));
        assertThat(result.path("remoteChecked").asBoolean()).isFalse();
        assertThat(result.path("conflicts").size()).isEqualTo(1);
        assertThat(result.at("/conflicts/0/configurationId").asText()).isEqualTo("3403");
        assertThat(result.at("/conflicts/0/taskNumber").asText()).isEqualTo(owner.at("/batch/taskNumber").asText());
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?",issue)).isEqualTo(before);
        verifyNoInteractions(executor,standalone);
    }
    @Test void creationCannotBypassLocalDuplicateGuardOrSilentlyReuse() throws Exception {
        var owner=setup("GUARD");long issue=owner.at("/issues/0/id").asLong();registered(issue);
        var alias=group(login(),marketOf(issue),"DUP_ALIAS_GUARD");long target=alias.at("/issues/0/id").asLong();
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+target+"/remote-create").session(login()).with(csrf()))
            .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("LOCAL_REDEMPTION_DUPLICATE"));
        assertThat(jdbc.queryForObject("select reused_from_issue_id from erp_compat_redemption_code_issues where id=?",Long.class,target)).isNull();
        verifyNoInteractions(executor,standalone);
    }
    @Test void importedMixedCaseCodesAndDeletedHistoryRemainConflictsButOtherMarketsDoNot() throws Exception {
        var owner=setup("CASE");long issue=owner.at("/issues/0/id").asLong();registered(issue);
        jdbc.update("update erp_compat_redemption_code_issues set redemption_code='0905RAJ7DAYS0',remote_deletion_state='DELETED' where id=?",issue);
        var result=send(login(),"/api/v1/redemption-campaigns/groups/duplicate-check",draft(marketOf(issue),false));
        assertThat(result.at("/conflicts/0/code").asText()).isEqualTo("0905raj7days0");
        assertThat(result.at("/conflicts/0/localStatus").asText()).isEqualTo("DELETED");
        var other=setup("OTHER");
        assertThat(send(login(),"/api/v1/redemption-campaigns/groups/duplicate-check",draft(marketOf(other.at("/issues/0/id").asLong()),false)).path("conflicts").isEmpty()).isTrue();
        verifyNoInteractions(executor,standalone);
    }
    @Test void unknownCreationWithoutAnIdStillBlocksAnotherTaskLocally() throws Exception {
        var owner=setup("UNKNOWN");long issue=owner.at("/issues/0/id").asLong();
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='FAILED',remote_error='远端创建结果未确认：请求超时' where id=?",issue);
        var result=send(login(),"/api/v1/redemption-campaigns/groups/duplicate-check",draft(marketOf(issue),false));
        assertThat(result.path("conflicts").size()).isEqualTo(1);
        verifyNoInteractions(executor,standalone);
    }

    @Test void confirmedHistoricalDuplicateCanCreateNewConfigurationWithoutChangingOldFacts() throws Exception {
        var owner=setup("CONFIRM");long oldId=owner.at("/issues/0/id").asLong();registered(oldId);
        jdbc.update("update erp_compat_redemption_code_issues set redemption_code='0905RAJ7DAYS0',workflow_status='CODE_IMPORTED',state='GENERATED' where id=?",oldId);
        var before=jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?",oldId);
        var alias=group(login(),marketOf(oldId),"CONFIRM_NEW");long target=alias.at("/issues/0/id").asLong();
        var preview=send(login(),"/api/v1/redemption-campaigns/groups/duplicate-check",draft(marketOf(oldId),false));
        String fingerprint=preview.at("/conflicts/0/reviewFingerprint").asText();
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any()))
            .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("9801","new-group",null));
        when(executor.checkReuse(anyLong(),eq(target),eq("9801"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),anyString()))
            .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("9801",true,java.util.List.of(),"new-group",java.math.BigDecimal.ONE,java.math.BigDecimal.valueOf(3)));
        String review=mapper.writeValueAsString(java.util.Map.of("confirmed",true,"fingerprints",java.util.Map.of(Long.toString(oldId),fingerprint)));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+target+"/remote-create").session(login()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(review))
            .andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("9801"));
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?",oldId)).isEqualTo(before);
        assertThat(jdbc.queryForObject("select reused_from_issue_id from erp_compat_redemption_code_issues where id=?",Long.class,target)).isNull();
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_audit_logs where action='REDEMPTION_DUPLICATES_REVIEW_CONFIRMED' and entity_id=?",Integer.class,Long.toString(target))).isEqualTo(1);
        // A second bare create is rejected by the existing receipt guard; it cannot submit another create.
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+target+"/remote-create").session(login()).with(csrf()))
            .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REMOTE_CREATE_RECONCILIATION_REQUIRED"));
        verify(executor,times(1)).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        verifyNoInteractions(standalone);
    }

    @Test void confirmationDoesNotAuthorizeNewOrChangedHistoricalConflicts() throws Exception {
        var owner=setup("STALE_REVIEW");long oldId=owner.at("/issues/0/id").asLong();registered(oldId);
        var alias=group(login(),marketOf(oldId),"STALE_REVIEW_NEW");long target=alias.at("/issues/0/id").asLong();
        var preview=send(login(),"/api/v1/redemption-campaigns/groups/duplicate-check",draft(marketOf(oldId),false));
        var fingerprints=java.util.Map.of(Long.toString(oldId),preview.at("/conflicts/0/reviewFingerprint").asText());
        for(boolean confirmed:java.util.List.of(false,true)) {
            if(confirmed) jdbc.update("update erp_compat_redemption_code_issues set bonus_max_amount=bonus_max_amount+1 where id=?",oldId);
            String review=mapper.writeValueAsString(java.util.Map.of("confirmed",confirmed,"fingerprints",fingerprints));
            mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+target+"/remote-create?retryFailed=true").session(login()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(review))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("LOCAL_REDEMPTION_DUPLICATE"));
        }
        verifyNoInteractions(executor,standalone);
    }

    @Test void remoteOptionFindsUnregisteredCodesAndScansOnlyOnceForTheMarket() throws Exception {
        var owner=setup("REMOTE");long market=marketOf(owner.at("/issues/0/id").asLong());
        when(executor.checkDuplicateCodes(anyLong(),anyList())).thenReturn(java.util.List.of(new UnifiedRedemptionRemoteExecutorClient.DuplicateCode("0905raj7days0","9800")));
        var result=send(login(),"/api/v1/redemption-campaigns/groups/duplicate-check",draft(market,true).replace("2026-09-05\",\"deposits", "2026-09-30\",\"deposits"));
        assertThat(result.path("remoteChecked").asBoolean()).isTrue();
        assertThat(result.at("/conflicts/0/source").asText()).isEqualTo("REMOTE");
        verify(executor,times(1)).checkDuplicateCodes(anyLong(),argThat(codes->codes.size()==26));
        verifyNoInteractions(standalone);
    }
    @Test void remoteFailureIsNotReportedAsNoDuplicates() throws Exception {
        var owner=setup("REMOTE_FAIL");long market=marketOf(owner.at("/issues/0/id").asLong());
        when(executor.checkDuplicateCodes(anyLong(),anyList())).thenThrow(com.rajads.erp.shared.ApiException.conflict("REMOTE_DUPLICATE_CHECK_REJECTED","查重超时"));
        mvc.perform(post("/api/v1/redemption-campaigns/groups/duplicate-check").session(login()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(draft(market,true)))
            .andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("REMOTE_DUPLICATE_CHECK_REJECTED"));
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
    }
    @Test void inDraftDuplicateCodesAreRejectedWithoutAnyRemoteRequest() throws Exception {
        var owner=setup("INPUT");long market=marketOf(owner.at("/issues/0/id").asLong());
        mvc.perform(post("/api/v1/redemption-campaigns/groups/duplicate-check").session(login()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(draft(market,true).replace("[0]","[0,0]")))
            .andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("DUPLICATE_SPECIAL_CODE"));
        verifyNoInteractions(executor,standalone);
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
        return send(session, "/api/v1/redemption-campaigns/groups", groupRequest(market, code, keyNumber));
    }

    private String groupRequest(long market, String code, int keyNumber) {
        return """
                {"code":"%s","name":"%s","claimDateFrom":"2026-09-05","claimDateTo":"2026-09-05","lookbackDays":7,
                 "tiers":[{"displayName":"全部用户","minDepositAmount":0,"bonusAmount":1,"bonusMaxAmount":3,"sortOrder":1}],
                 "remoteMarketId":%s,"redemptionType":"%s","tierUserTypes":["ALL_USERS"],"tierLabelIds":[[]],
                 "remoteOptions":{"publishEnvironment":"test","flowTimes":5,"creationIntervalSeconds":5,"keyNumber":%d,"singleUserLimit":1,"singleKeyLimit":3000,"requireBindBankCard":false,"requireBindPhone":true,"checkUuid":true,"uuidRewardLimit":1,"checkLoginIp":true,"loginIpRewardLimit":1,"checkRegisterIp":true,"registerIpRewardLimit":1}}
                """.formatted(code, code, market, keyNumber == 1 ? "SEVEN_DAY_DEPOSIT" : "AGENT", keyNumber);
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
