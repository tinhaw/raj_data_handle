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
