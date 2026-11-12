package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.rajads.erp.config.RemoteOperationGate;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.web.servlet.MockMvc;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties = "spring.jpa.open-in-view=false")
@AutoConfigureMockMvc
class RedemptionCodeNamingHttpTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;
    @Autowired JdbcTemplate jdbc;
    @Autowired RedemptionCodeIssueRepository issues;
    @Autowired RedemptionRecoveryService recovery;
    @MockBean RemoteGiftCodeBackendClient standalone;
    @MockBean RemoteOperationGate gate;
    @MockBean UnifiedRedemptionRemoteExecutorClient executor;

    @Test void namingOnlyChangesTheTenThousandTierForBothSpecialTypes() {
        var day = LocalDate.of(2026, 11, 16);
        for (var type : List.of(RedemptionCodeType.PREVIOUS_DAY_DEPOSIT, RedemptionCodeType.SEVEN_DAY_DEPOSIT)) {
            var prefix = type == RedemptionCodeType.PREVIOUS_DAY_DEPOSIT ? "1116raj" : "1116raj7days";
            assertThat(type.specialCode(day, new BigDecimal("10000.00"), RedemptionCodeNaming.TEN_K)).isEqualTo(prefix + "10K");
            assertThat(type.specialCode(day, new BigDecimal("10000"), null)).isEqualTo(prefix + "10000");
            for (long deposit : new long[]{0, 100, 200, 1000, 3000, 10001, 100000})
                assertThat(type.specialCode(day, BigDecimal.valueOf(deposit), RedemptionCodeNaming.TEN_K))
                        .isEqualTo(type.specialCode(day, BigDecimal.valueOf(deposit)));
            assertThatThrownBy(() -> type.specialCode(day, new BigDecimal("10000.1"), RedemptionCodeNaming.TEN_K))
                    .hasMessageContaining("非负整数");
        }
    }

    @Test void persistedChoiceSurvivesFreshSessionRetryAndActualRewardReadback() throws Exception {
        long market = market("RETRY");
        var made = group(market, "RETRY", "TEN_K", "PREVIOUS_DAY_DEPOSIT");
        long id = made.at("/issues/0/id").asLong(), batch = made.at("/batch/id").asLong();
        mvc.perform(get("/api/v1/redemption-campaigns/batches/"+batch).session(login()))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.batch.specialCodeNaming").value("TEN_K"));
        assertThat(made.at("/issues/0/minDepositAmount").decimalValue()).isEqualByComparingTo("10000");
        jdbc.update("update erp_compat_redemption_code_issues set workflow_status='FAILED',remote_error='前次创建未提交' where id=?", id);
        when(executor.create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),eq("1116raj10K")))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.CreatedConfiguration("98001", "naming-group", null));
        when(executor.checkReuse(anyLong(),eq(id),eq("98001"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),eq("1116raj10K")))
                .thenReturn(new UnifiedRedemptionRemoteExecutorClient.ReuseCheck("98001", true, List.of(), "naming-group", new BigDecimal("37"), new BigDecimal("177")));
        mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+id+"/remote-create?retryFailed=true").session(login()).with(csrf()))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.issues[0].workflowStatus").value("CREATED"));
        verify(executor).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),eq("1116raj10K"));
        verify(executor).checkReuse(anyLong(),eq(id),eq("98001"),anyString(),any(),any(),any(),anyList(),any(),any(),any(),eq("1116raj10K"));
        assertThat(recovery.policySnapshot(id).code()).isEqualTo("1116raj10K");
        assertThat(recovery.policySnapshot(id).bonusMin()).isEqualByComparingTo("37");
        verifyNoInteractions(standalone);
    }

    @Test void originalAndTenKHaveIndependentLocalChecksAndReuseCandidates() throws Exception {
        long market = market("IDENTITY");
        var original = group(market, "ORIGINAL", null, "SEVEN_DAY_DEPOSIT");
        long oldId = original.at("/issues/0/id").asLong();
        registered(oldId, "98002");
        var before = jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", oldId);
        assertThat(original.at("/batch/specialCodeNaming").asText()).isEqualTo("ORIGINAL");
        assertThat(check(market, "TEN_K", false).path("conflicts")).isEmpty();
        assertThat(check(market, null, false).at("/conflicts/0/code").asText()).isEqualTo("1116raj7days10000");
        var compact = group(market, "COMPACT", "TEN_K", "SEVEN_DAY_DEPOSIT");
        long newId = compact.at("/issues/0/id").asLong();
        assertThat(issues.findReuseCandidates(market,newId,"1116raj7days10k",RedemptionCodeType.SEVEN_DAY_DEPOSIT,11,16,
                new BigDecimal("10000"),RedemptionCodeNaming.TEN_K)).isEmpty();
        registered(newId, "98003");
        assertThat(check(market, "TEN_K", false).at("/conflicts/0/issueId").asLong()).isEqualTo(newId);
        assertThat(check(market, "ORIGINAL", false).at("/conflicts/0/issueId").asLong()).isEqualTo(oldId);
        assertThat(recovery.policySnapshot(oldId).code()).isEqualTo("1116raj7days10000");
        assertThat(recovery.policySnapshot(newId).code()).isEqualTo("1116raj7days10K");
        assertThat(jdbc.queryForMap("select * from erp_compat_redemption_code_issues where id=?", oldId)).isEqualTo(before);
        verifyNoInteractions(executor, standalone);
    }

    @Test void bothNamingModesMayStillReuseAnUnchangedLowerTier() throws Exception {
        long market = market("LOWER");
        var input = input(market,"LOWER_OWNER",null,"SEVEN_DAY_DEPOSIT");
        ((ObjectNode)input.at("/tiers/0")).put("minDepositAmount",200);
        long owner = send("/api/v1/redemption-campaigns/groups",input).at("/issues/0/id").asLong();
        registered(owner,"98004");
        assertThat(issues.findReuseCandidates(market,-1L,"1116raj7days200",RedemptionCodeType.SEVEN_DAY_DEPOSIT,11,16,
                new BigDecimal("200"),RedemptionCodeNaming.TEN_K)).extracting(RedemptionCodeIssue::getId).containsExactly(owner);
    }

    @Test void optionalRemoteCheckUsesSelectedSpellingAndNeverCreates() throws Exception {
        long market=market("REMOTE");
        when(executor.checkDuplicateCodes(anyLong(),anyList())).thenReturn(List.of());
        assertThat(check(market,"TEN_K",true).path("remoteChecked").asBoolean()).isTrue();
        verify(executor).checkDuplicateCodes(anyLong(),eq(List.of("1116raj7days10k")));
        verify(executor,never()).create(any(),any(),any(),any(),any(),any(),any(),any(),any(),any(),any());
        verifyNoInteractions(standalone);
    }

    @Test void pendingReviewUsesTheSavedModeEvenAfterRefresh() throws Exception {
        long market=market("REVIEW");
        var owner=group(market,"REVIEW_OWNER","TEN_K","SEVEN_DAY_DEPOSIT");
        long ownerId=owner.at("/issues/0/id").asLong();registered(ownerId,"98005");
        var next=group(market,"REVIEW_NEXT","TEN_K","SEVEN_DAY_DEPOSIT");
        var preview=send("/api/v1/redemption-campaigns/batches/"+next.at("/batch/id").asLong()+"/creation-duplicate-check",mapper.createObjectNode());
        assertThat(preview.at("/conflicts/0/code").asText()).isEqualTo("1116raj7days10k");
        assertThat(preview.at("/conflicts/0/issueId").asLong()).isEqualTo(ownerId);
        verifyNoInteractions(executor,standalone);
    }

    @Test void invalidNamingDoesNotCreateATaskOrCallRemote() throws Exception {
        long market=market("INVALID");
        int before=jdbc.queryForObject("select count(*) from erp_compat_redemption_code_tasks",Integer.class);
        mvc.perform(post("/api/v1/redemption-campaigns/groups").session(login()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                .content(input(market,"INVALID","CUSTOM","SEVEN_DAY_DEPOSIT").toString())).andExpect(status().isBadRequest());
        assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_code_tasks",Integer.class)).isEqualTo(before);
        verifyNoInteractions(executor,standalone);
    }

    private void registered(long id,String cfg) { jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id=?,workflow_status='CREATED' where id=?",cfg,id); }
    private JsonNode check(long market,String naming,boolean remote) throws Exception {
        ObjectNode input=mapper.createObjectNode();input.put("checkRemote",remote);
        ObjectNode m=input.putArray("markets").addObject();m.put("marketId",market);m.put("redemptionType","SEVEN_DAY_DEPOSIT");
        m.put("from","2026-11-16");m.put("to","2026-11-16");m.putArray("deposits").add(10000);
        if(naming!=null)m.put("specialCodeNaming",naming);
        return send("/api/v1/redemption-campaigns/groups/duplicate-check",input);
    }
    private JsonNode group(long market,String key,String naming,String type) throws Exception { return send("/api/v1/redemption-campaigns/groups",input(market,key,naming,type)); }
    private ObjectNode input(long market,String key,String naming,String type) throws Exception {
        ObjectNode input=(ObjectNode)mapper.readTree("""
            {"code":"NAMING_%s","name":"Naming %s","claimDateFrom":"2026-11-16","claimDateTo":"2026-11-16","lookbackDays":7,
             "tiers":[{"displayName":"10000+","minDepositAmount":10000,"bonusAmount":37,"bonusMaxAmount":177,"sortOrder":1}],
             "remoteMarketId":%d,"redemptionType":"%s","tierUserTypes":["ALL_USERS"],"tierLabelIds":[[]],
             "remoteOptions":{"publishEnvironment":"test","flowTimes":5,"creationIntervalSeconds":5,"keyNumber":1,"singleUserLimit":1,"singleKeyLimit":3000,"requireBindBankCard":false,"requireBindPhone":true,"checkUuid":true,"uuidRewardLimit":1,"checkLoginIp":true,"loginIpRewardLimit":1,"checkRegisterIp":true,"registerIpRewardLimit":1}}
            """.formatted(key,key,market,type));
        if(naming!=null)input.put("specialCodeNaming",naming);return input;
    }
    private long market(String key) throws Exception {
        String code="NAMING_"+key;
        long id=send("/api/v1/redemption-remote-markets",mapper.readTree("""
            {"code":"%s","name":"%s","baseUrl":"https://naming-%s.example","enabled":true}
            """.formatted(code,code,key.toLowerCase()))).path("id").asLong();
        send("/api/v1/redemption-remote-connections",mapper.readTree("""
            {"username":"naming","marketId":%d,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
            """.formatted(id)));return id;
    }
    private JsonNode send(String path,JsonNode input) throws Exception {
        var result=mvc.perform(post(path).session(login()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(input.toString()))
                .andExpect(status().isOk()).andReturn();
        return mapper.readTree(result.getResponse().getContentAsString()).path("data");
    }
    private MockHttpSession login() throws Exception {
        return (MockHttpSession)mvc.perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON)
                .content("{\"username\":\"admin\",\"password\":\"admin123\"}")).andExpect(status().isOk()).andReturn().getRequest().getSession(false);
    }
}
