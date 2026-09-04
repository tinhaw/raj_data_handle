package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.config.RemoteOperationGate;
import com.rajads.erp.shared.ApiException;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@SpringBootTest
@AutoConfigureMockMvc
class RedemptionCampaignHttpTest {
    @Autowired private MockMvc mockMvc;
    @Autowired private ObjectMapper objectMapper;
    @MockBean private RemoteGiftCodeBackendClient remoteGiftCodeBackendClient;
    @MockBean private RemoteOperationGate remoteOperationGate;

    @Test
    void adminCanCreateTieredCampaign() throws Exception {
        MockHttpSession session = login();
        String request = """
                {"code":"deposit_7d_aug","name":"八月七天充值活动","lookbackDays":7,
                 "tiers":[
                   {"displayName":"入门档","minDepositAmount":100,"bonusAmount":17,"sortOrder":1},
                   {"displayName":"进阶档","minDepositAmount":500,"bonusAmount":57,"sortOrder":2}
                 ]}
                """;
        MvcResult created = mockMvc.perform(post("/api/v1/redemption-campaigns").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content(request))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.code").value("DEPOSIT_7D_AUG"))
                .andExpect(jsonPath("$.data.status").value("DRAFT"))
                .andExpect(jsonPath("$.data.tiers.length()").value(2))
                .andReturn();
        JsonNode body = objectMapper.readTree(created.getResponse().getContentAsString());
        long id = body.at("/data/id").asLong();

        mockMvc.perform(get("/api/v1/redemption-campaigns/" + id).session(session))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.tiers[0].minDepositAmount").value(100));
    }

    @Test
    void adminCanCreateAnActiveCodeGroupWithItsInitialRemoteBatch() throws Exception {
        MockHttpSession session = login();
        long marketId = data(mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"GROUP_CREATE_MARKET","name":"兑换码组测试盘口","baseUrl":"https://group-create.example.com","enabled":true}
                                """))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();
        long connectionId = data(mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"username":"group-create-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                                """.formatted(marketId)))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();
        when(remoteGiftCodeBackendClient.tags(any())).thenReturn(List.of(
                new RemoteGiftCodeBackendClient.RemoteTag(901091, "近7天充值100-499"),
                new RemoteGiftCodeBackendClient.RemoteTag(901092, "近7天充值500-1999")));

        MvcResult groupResult = mockMvc.perform(post("/api/v1/redemption-campaigns/groups").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"group_create_aug","name":"八月兑换码组","claimDateFrom":"2026-08-20","claimDateTo":"2026-08-21","lookbackDays":7,
                                 "tiers":[{"displayName":"近7天充值100-499","minDepositAmount":100,"bonusAmount":1,"bonusMaxAmount":3,"sortOrder":1},{"displayName":"近7天充值500-1999","minDepositAmount":500,"bonusAmount":5,"bonusMaxAmount":7,"sortOrder":2}],
                                 "remoteMarketId":%s,"redemptionType":"SEVEN_DAY_DEPOSIT","tierUserTypes":["LABEL_USERS","ALL_USERS"],"tierLabelIds":[[901091],[]],
                                 "remoteOptions":{"publishEnvironment":"test","flowTimes":5,"creationIntervalSeconds":5,"activityRecharge":500,"activityRechargeCount":3,"activityId":456,"keyNumber":1,"singleUserLimit":1,"singleKeyLimit":2,"requireBindBankCard":false,"requireBindPhone":true,"checkUuid":true,"uuidRewardLimit":1,"checkLoginIp":true,"loginIpRewardLimit":1,"checkRegisterIp":true,"registerIpRewardLimit":1}}
                                """.formatted(marketId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.status").value("CREATING"))
                .andExpect(jsonPath("$.data.batch.taskId").isNumber())
                .andExpect(jsonPath("$.data.batch.expectedCodeCount").value(4))
                .andExpect(jsonPath("$.data.batch.remoteConnectionId").value(connectionId))
                .andExpect(jsonPath("$.data.batch.remoteOptions.activityRecharge").value(500))
                .andExpect(jsonPath("$.data.batch.remoteOptions.activityRechargeCount").value(3))
                .andExpect(jsonPath("$.data.batch.remoteOptions.activityId").value(456))
                .andExpect(jsonPath("$.data.batch.remoteOptions.creationIntervalSeconds").value(5))
                .andExpect(jsonPath("$.data.issues[0].remoteLabelIds[0]").value(901091))
                .andExpect(jsonPath("$.data.issues[1].remoteLabelIds").isEmpty())
                .andReturn();

        long allUsersIssueId = data(groupResult).at("/issues/1/id").asLong();
        when(remoteGiftCodeBackendClient.create(any(), any())).thenReturn(new RemoteGiftCodeBackendClient.CreatedConfiguration("all-users-seven-day", null));
        when(remoteGiftCodeBackendClient.findGroupKey(any(), any(), any())).thenReturn("all-users-seven-day-group");
        mockMvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + allUsersIssueId + "/remote-create").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()))
                .andExpect(status().isOk());
        ArgumentCaptor<RemoteGiftCodeBackendClient.CreateConfigurationRequest> allUsersRequest = ArgumentCaptor.forClass(RemoteGiftCodeBackendClient.CreateConfigurationRequest.class);
        verify(remoteGiftCodeBackendClient).create(any(), allUsersRequest.capture());
        assertThat(allUsersRequest.getValue().allUsers()).isTrue();
        assertThat(allUsersRequest.getValue().labelIds()).isEmpty();

        mockMvc.perform(get("/api/v1/redemption-campaigns").session(session))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[0].code").value("GROUP_CREATE_AUG"))
                .andExpect(jsonPath("$.data[0].status").value("ACTIVE"));
    }

    @Test
    void previousDayCodeGroupUsesDailyTagsAndAllUsersForItsZeroTier() throws Exception {
        MockHttpSession session = login();
        long marketId = data(mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"PREVIOUS_DAY_MARKET","name":"前一天充值测试盘口","baseUrl":"https://previous-day.example.com","enabled":true}
                                """))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();
        mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"username":"previous-day-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                                """.formatted(marketId)))
                .andExpect(status().isOk());
        when(remoteGiftCodeBackendClient.tags(any())).thenReturn(List.of(
                new RemoteGiftCodeBackendClient.RemoteTag(901991, "日充值200-999")));

        MvcResult groupResult = mockMvc.perform(post("/api/v1/redemption-campaigns/groups").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"previous_day_aug","name":"前一天充值兑换码组","claimDateFrom":"2026-08-18","claimDateTo":"2026-08-18","lookbackDays":7,
                                 "tiers":[{"displayName":"前一天充值 0（所有用户）","minDepositAmount":0,"bonusAmount":1,"bonusMaxAmount":3,"sortOrder":1},{"displayName":"前一天充值 200–999","minDepositAmount":200,"bonusAmount":7,"bonusMaxAmount":9,"sortOrder":2}],
                                 "remoteMarketId":%s,"redemptionType":"PREVIOUS_DAY_DEPOSIT","tierUserTypes":["ALL_USERS","LABEL_USERS"],"tierLabelIds":[[],[901991]],
                                 "remoteOptions":{"publishEnvironment":"test","flowTimes":5,"creationIntervalSeconds":5,"keyNumber":1,"singleUserLimit":1,"singleKeyLimit":3000,"requireBindBankCard":false,"requireBindPhone":true,"checkUuid":true,"uuidRewardLimit":1,"checkLoginIp":true,"loginIpRewardLimit":1,"checkRegisterIp":true,"registerIpRewardLimit":1}}
                                """.formatted(marketId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.redemptionType").value("PREVIOUS_DAY_DEPOSIT"))
                .andExpect(jsonPath("$.data.batch.lookbackDays").value(1))
                .andExpect(jsonPath("$.data.issues[0].depositWindowStart").value("2026-08-17"))
                .andExpect(jsonPath("$.data.issues[0].depositWindowEnd").value("2026-08-17"))
                .andExpect(jsonPath("$.data.issues[0].remoteLabelIds").isEmpty())
                .andExpect(jsonPath("$.data.issues[1].remoteLabelIds[0]").value(901991))
                .andReturn();

        long allUsersIssueId = data(groupResult).at("/issues/0/id").asLong();
        when(remoteGiftCodeBackendClient.create(any(), any())).thenReturn(new RemoteGiftCodeBackendClient.CreatedConfiguration("previous-day-zero", null));
        when(remoteGiftCodeBackendClient.findGroupKey(any(), any(), any())).thenReturn("previous-day-group");
        mockMvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + allUsersIssueId + "/remote-create").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()))
                .andExpect(status().isOk());
        ArgumentCaptor<RemoteGiftCodeBackendClient.CreateConfigurationRequest> createRequest = ArgumentCaptor.forClass(RemoteGiftCodeBackendClient.CreateConfigurationRequest.class);
        verify(remoteGiftCodeBackendClient).create(any(), createRequest.capture());
        assertThat(createRequest.getValue().description()).isEqualTo("NEW-818存款0");
        assertThat(createRequest.getValue().allUsers()).isTrue();
        assertThat(createRequest.getValue().labelIds()).isEmpty();
    }

    @Test
    void rewardTierPresetMustBeResavedAfterAnOperatorSyncsRemoteTags() throws Exception {
        MockHttpSession session = login();
        long marketId = data(mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"PRESET_MARKET","name":"预设测试盘口","baseUrl":"https://preset.example.com","enabled":true}
                                """))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();
        long connectionId = data(mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"username":"preset-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                                """.formatted(marketId)))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();
        when(remoteGiftCodeBackendClient.tags(any())).thenReturn(List.of(
                new RemoteGiftCodeBackendClient.RemoteTag(901092, "(901092)近7天充值总金额500-1999")));

        mockMvc.perform(post("/api/v1/redemption-remote-connections/" + connectionId + "/tags/sync").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.tags[0].id").value(901092))
                .andExpect(jsonPath("$.data.presetStale").value(false));

        mockMvc.perform(put("/api/v1/redemption-remote-connections/" + connectionId + "/reward-tier-preset").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"tiers":[{"labelIds":[901092],"displayName":"近7天充值总金额500-1999","minDepositAmount":500,"bonusAmount":5,"bonusMaxAmount":7}],
                                 "tagSnapshot":[{"id":901092,"name":"(901092)近7天充值总金额500-1999"}]}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.exists").value(true))
                .andExpect(jsonPath("$.data.stale").value(false))
                .andExpect(jsonPath("$.data.tiers[0].bonusMaxAmount").value(7));

        mockMvc.perform(post("/api/v1/redemption-remote-connections/" + connectionId + "/tags/sync").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.presetStale").value(true));
        mockMvc.perform(get("/api/v1/redemption-remote-connections/" + connectionId + "/reward-tier-preset").session(session))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.exists").value(true))
                .andExpect(jsonPath("$.data.stale").value(true));
    }

    @Test
    void adminCanTrackTheManualRemoteCreationPublishDownloadAndImportWorkflow() throws Exception {
        MockHttpSession session = login();
        MvcResult campaignResult = mockMvc.perform(post("/api/v1/redemption-campaigns").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"manual_batch_aug","name":"人工领码活动","lookbackDays":7,
                                 "tiers":[
                                   {"displayName":"充值100","minDepositAmount":100,"bonusAmount":5,"bonusMaxAmount":17,"sortOrder":1},
                                   {"displayName":"充值500","minDepositAmount":500,"bonusAmount":11,"bonusMaxAmount":57,"sortOrder":2}
                                 ]}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.tiers[0].bonusMaxAmount").value(17))
                .andReturn();
        JsonNode campaign = data(campaignResult);
        long campaignId = campaign.path("id").asLong();

        mockMvc.perform(patch("/api/v1/redemption-campaigns/" + campaignId).session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"ACTIVE\",\"rowVersion\":" + campaign.path("rowVersion").asLong() + "}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.status").value("ACTIVE"));

        MvcResult batchResult = mockMvc.perform(post("/api/v1/redemption-campaigns/batches").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"campaignId\":" + campaignId + ",\"claimDateFrom\":\"2026-08-20\",\"claimDateTo\":\"2026-08-21\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.expectedCodeCount").value(4))
                .andExpect(jsonPath("$.data.issues.length()").value(4))
                .andReturn();
        JsonNode detail = data(batchResult);
        long batchId = detail.at("/batch/id").asLong();
        for (int index = 0; index < 4; index++) {
            JsonNode issue = detail.at("/issues/" + index);
            MvcResult configurationResult = mockMvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issue.path("id").asLong() + "/remote-configuration")
                            .session(session).with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                            .content("{\"remoteConfigurationId\":\"remote-" + (index + 1) + "\",\"rowVersion\":" + issue.path("rowVersion").asLong() + "}"))
                    .andExpect(status().isOk())
                    .andReturn();
            detail = data(configurationResult);
        }
        assertThat(detail.at("/batch/status").asText()).isEqualTo("READY_TO_PUBLISH");

        MvcResult publishedResult = mockMvc.perform(post("/api/v1/redemption-campaigns/batches/" + batchId + "/publish").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"rowVersion\":" + detail.at("/batch/rowVersion").asLong() + "}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.status").value("PUBLISHED"))
                .andReturn();

        MvcResult importResult = mockMvc.perform(post("/api/v1/redemption-campaigns/batches/" + batchId + "/codes/import").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"rows":[
                                  {"remoteConfigurationId":"remote-1","redemptionCode":"CODE100A"},
                                  {"remoteConfigurationId":"remote-2","redemptionCode":"CODE500A"},
                                  {"remoteConfigurationId":"remote-3","redemptionCode":"CODE100B"},
                                  {"remoteConfigurationId":"remote-4","redemptionCode":"CODE500B"}
                                ]}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.importedCount").value(4))
                .andExpect(jsonPath("$.data.batch.status").value("COMPLETED"))
                .andExpect(jsonPath("$.data.issues[0].redemptionCode").value("CODE100A"))
                .andReturn();
        assertThat(data(importResult).at("/batch/importedCount").asInt()).isEqualTo(4);

        mockMvc.perform(get("/api/v1/redemption-campaigns/batches/" + batchId + "/export").session(session))
                .andExpect(status().isOk())
                .andExpect(result -> assertThat(result.getResponse().getContentAsByteArray()).isNotEmpty());
    }

    @Test
    void adminCanRunTheConfiguredRemoteCreatePublishAndDownloadSequence() throws Exception {
        MockHttpSession session = login();
        MvcResult marketResult = mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"REMOTE_TEST_MARKET","name":"Remote Test Market","baseUrl":"https://remote.example.com","enabled":true}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.baseUrl").value("https://remote.example.com"))
                .andReturn();
        long marketId = data(marketResult).path("id").asLong();
        MvcResult connectionResult = mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"username":"remote-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                                """.formatted(marketId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.username").value("remote-admin"))
                .andExpect(jsonPath("$.data.hasPassword").value(true))
                .andExpect(jsonPath("$.data.hasTotpSecret").value(true))
                .andExpect(jsonPath("$.data.marketName").value("Remote Test Market"))
                .andReturn();
        long connectionId = data(connectionResult).path("id").asLong();

        MvcResult campaignResult = mockMvc.perform(post("/api/v1/redemption-campaigns").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"remote_flow_aug","name":"自动远端领码","lookbackDays":7,
                                 "tiers":[{"displayName":"充值100","minDepositAmount":100,"bonusAmount":5,"bonusMaxAmount":17,"sortOrder":1}]}
                                """))
                .andExpect(status().isOk()).andReturn();
        JsonNode campaign = data(campaignResult);
        long campaignId = campaign.path("id").asLong();
        mockMvc.perform(patch("/api/v1/redemption-campaigns/" + campaignId).session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"ACTIVE\",\"rowVersion\":" + campaign.path("rowVersion").asLong() + "}"))
                .andExpect(status().isOk());

        long tierId = campaign.at("/tiers/0/id").asLong();
        MvcResult batchResult = mockMvc.perform(post("/api/v1/redemption-campaigns/batches").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"campaignId\":" + campaignId + ",\"claimDateFrom\":\"2026-08-22\",\"claimDateTo\":\"2026-08-22\",\"remoteConnectionId\":" + connectionId + ",\"tierLabelIds\":{\"" + tierId + "\":[901026]},\"remoteOptions\":{\"publishEnvironment\":\"test\",\"flowTimes\":5,\"creationIntervalSeconds\":5,\"keyNumber\":1,\"singleUserLimit\":1,\"singleKeyLimit\":2000,\"requireBindBankCard\":false,\"requireBindPhone\":true,\"checkUuid\":true,\"uuidRewardLimit\":1,\"checkLoginIp\":true,\"loginIpRewardLimit\":1,\"checkRegisterIp\":true,\"registerIpRewardLimit\":1}}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.remoteConnectionName").value("remote-admin"))
                .andExpect(jsonPath("$.data.batch.remoteOptions.flowTimes").value(5))
                .andReturn();
        JsonNode detail = data(batchResult);
        long issueId = detail.at("/issues/0/id").asLong();
        when(remoteGiftCodeBackendClient.create(any(), any())).thenReturn(new RemoteGiftCodeBackendClient.CreatedConfiguration("1563", null));
        when(remoteGiftCodeBackendClient.findGroupKey(any(), any(), any())).thenReturn("group-1563");
        MvcResult createdResult = mockMvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issueId + "/remote-create").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.issues[0].remoteConfigurationId").value("1563"))
                .andExpect(jsonPath("$.data.batch.status").value("READY_TO_PUBLISH"))
                .andReturn();
        ArgumentCaptor<RemoteGiftCodeBackendClient.CreateConfigurationRequest> createRequest = ArgumentCaptor.forClass(RemoteGiftCodeBackendClient.CreateConfigurationRequest.class);
        verify(remoteGiftCodeBackendClient).create(any(), createRequest.capture());
        assertThat(createRequest.getValue().description()).isEqualTo("NEW-815到821存款100");
        JsonNode createdDetail = data(createdResult);
        when(remoteGiftCodeBackendClient.publishAll(any(), any(), anyBoolean(), any())).thenReturn("17687");
        String scheduledTime = LocalDateTime.now(ZoneId.of("Asia/Kolkata")).plusHours(1).withNano(0)
                .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
        MvcResult scheduledResult = mockMvc.perform(post("/api/v1/redemption-campaigns/batches/" + createdDetail.at("/batch/id").asLong() + "/remote-publish").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"rowVersion\":" + createdDetail.at("/batch/rowVersion").asLong() + ",\"mode\":\"SCHEDULED\",\"scheduledTime\":\"" + scheduledTime + "\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.remotePublishTaskId").value("17687"))
                .andExpect(jsonPath("$.data.batch.status").value("PUBLISHED"))
                .andExpect(jsonPath("$.data.batch.remotePublishMode").value("SCHEDULED"))
                .andReturn();
        JsonNode scheduledDetail = data(scheduledResult);
        MvcResult cancelledResult = mockMvc.perform(post("/api/v1/redemption-campaigns/batches/" + createdDetail.at("/batch/id").asLong() + "/remote-publish/cancel").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"rowVersion\":" + scheduledDetail.at("/batch/rowVersion").asLong() + "}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.status").value("READY_TO_PUBLISH"))
                .andExpect(jsonPath("$.data.batch.remotePublishNote").value("已人工撤销定时发布，不再进行后续自动定时发布尝试"))
                .andReturn();
        JsonNode cancelledDetail = data(cancelledResult);
        verify(remoteGiftCodeBackendClient).cancelScheduledPublish(any(), any());

        MvcResult publishedResult = mockMvc.perform(post("/api/v1/redemption-campaigns/batches/" + createdDetail.at("/batch/id").asLong() + "/remote-publish").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"rowVersion\":" + cancelledDetail.at("/batch/rowVersion").asLong() + ",\"mode\":\"IMMEDIATE\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.remotePublishTaskId").value("17687"))
                .andExpect(jsonPath("$.data.batch.remotePublishMode").value("IMMEDIATE"))
                .andExpect(jsonPath("$.data.batch.remotePublishNote").value("立即发布"))
                .andReturn();
        assertThat(data(publishedResult).at("/batch/status").asText()).isEqualTo("PUBLISHED");

        when(remoteGiftCodeBackendClient.downloadCode(any(), any())).thenReturn("REMOTE-CODE-1");
        mockMvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issueId + "/remote-download").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.batch.status").value("COMPLETED"))
                .andExpect(jsonPath("$.data.issues[0].redemptionCode").value("REMOTE-CODE-1"));

        mockMvc.perform(get("/api/v1/redemption-campaigns/batches/" + createdDetail.at("/batch/id").asLong() + "/export").session(session))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Disposition", org.hamcrest.Matchers.containsString("filename*=UTF-8''redemption-codes-Remote%20Test%20Market-2026-08-22_to_2026-08-22.xlsx")));

        mockMvc.perform(delete("/api/v1/redemption-remote-connections/" + connectionId).session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"rowVersion\":" + data(connectionResult).path("rowVersion").asLong() + "}"))
                .andExpect(status().isConflict());
    }

    @Test
    void blockedRemoteCreateIsRecordedAsFailedWithoutCallingTheRemoteBackend() throws Exception {
        MockHttpSession session = login();
        long marketId = data(mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"GATE_BLOCKED_MARKET","name":"Gate Blocked Market","baseUrl":"https://gate-blocked.example.com","enabled":true}
                                """))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();
        long connectionId = data(mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"username":"gate-blocked-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                                """.formatted(marketId)))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();

        JsonNode campaign = data(mockMvc.perform(post("/api/v1/redemption-campaigns").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"gate_blocked_create","name":"远端开关拦截","lookbackDays":7,
                                 "tiers":[{"displayName":"充值100","minDepositAmount":100,"bonusAmount":5,"bonusMaxAmount":17,"sortOrder":1}]}
                                """))
                .andExpect(status().isOk()).andReturn());
        long campaignId = campaign.path("id").asLong();
        mockMvc.perform(patch("/api/v1/redemption-campaigns/" + campaignId).session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"ACTIVE\",\"rowVersion\":" + campaign.path("rowVersion").asLong() + "}"))
                .andExpect(status().isOk());

        long tierId = campaign.at("/tiers/0/id").asLong();
        JsonNode detail = data(mockMvc.perform(post("/api/v1/redemption-campaigns/batches").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"campaignId\":" + campaignId + ",\"claimDateFrom\":\"2026-09-05\",\"claimDateTo\":\"2026-09-05\",\"remoteConnectionId\":" + connectionId + ",\"tierLabelIds\":{\"" + tierId + "\":[901026]},\"remoteOptions\":{\"publishEnvironment\":\"test\",\"flowTimes\":5,\"creationIntervalSeconds\":5,\"keyNumber\":1,\"singleUserLimit\":1,\"singleKeyLimit\":2000,\"requireBindBankCard\":false,\"requireBindPhone\":true,\"checkUuid\":true,\"uuidRewardLimit\":1,\"checkLoginIp\":true,\"loginIpRewardLimit\":1,\"checkRegisterIp\":true,\"registerIpRewardLimit\":1}}"))
                .andExpect(status().isOk()).andReturn());
        long batchId = detail.at("/batch/id").asLong();
        long issueId = detail.at("/issues/0/id").asLong();

        doThrow(ApiException.forbidden("ERP 兼容模块的远端操作尚未启用：remote_create"))
                .when(remoteOperationGate).requireEnabled("remote_create");
        mockMvc.perform(post("/api/v1/redemption-campaigns/code-tasks/" + issueId + "/remote-create").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()))
                .andExpect(status().isForbidden());

        mockMvc.perform(get("/api/v1/redemption-campaigns/batches/" + batchId).session(session))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.issues[0].workflowStatus").value("FAILED"))
                .andExpect(jsonPath("$.data.issues[0].state").value("FAILED"))
                .andExpect(jsonPath("$.data.issues[0].remoteError").value(org.hamcrest.Matchers.containsString("remote_create")));
        verifyNoInteractions(remoteGiftCodeBackendClient);
    }

    @Test
    void adminCanDeleteAnUnusedRemoteAccount() throws Exception {
        MockHttpSession session = login();
        MvcResult marketResult = mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"DELETE_ACCOUNT_MARKET","name":"删除账号测试盘口","baseUrl":"https://delete-account.example.com","enabled":true}
                                """))
                .andExpect(status().isOk())
                .andReturn();
        long marketId = data(marketResult).path("id").asLong();
        MvcResult connectionResult = mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"username":"delete-account-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                                """.formatted(marketId)))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode connection = data(connectionResult);

        mockMvc.perform(delete("/api/v1/redemption-remote-connections/" + connection.path("id").asLong()).session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"rowVersion\":" + connection.path("rowVersion").asLong() + "}"))
                .andExpect(status().isOk());
    }

    @Test
    void remoteUsernameIsUniqueWithinItsMarketOnly() throws Exception {
        MockHttpSession session = login();
        long firstMarketId = data(mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"USERNAME_SCOPE_A","name":"账号范围盘口 A","baseUrl":"https://username-scope-a.example.com","enabled":true}
                                """))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();
        long secondMarketId = data(mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"USERNAME_SCOPE_B","name":"账号范围盘口 B","baseUrl":"https://username-scope-b.example.com","enabled":true}
                                """))
                .andExpect(status().isOk()).andReturn()).path("id").asLong();

        String firstAccount = """
                {"username":"shared-remote-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                """.formatted(firstMarketId);
        String secondAccount = """
                {"username":"shared-remote-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                """.formatted(secondMarketId);
        mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content(firstAccount))
                .andExpect(status().isOk());
        mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content(secondAccount))
                .andExpect(status().isOk());
        mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content(firstAccount))
                .andExpect(status().isConflict());
    }

    @Test
    void remoteConnectionCheckPersistsLoginAndCheckStateTogether() throws Exception {
        MockHttpSession session = login();
        MvcResult marketResult = mockMvc.perform(post("/api/v1/redemption-remote-markets").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"code":"CHECK_ACCOUNT_MARKET","name":"检测账号盘口","baseUrl":"https://check-account.example.com","enabled":true}
                                """))
                .andExpect(status().isOk()).andReturn();
        long marketId = data(marketResult).path("id").asLong();
        MvcResult connectionResult = mockMvc.perform(post("/api/v1/redemption-remote-connections").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()).contentType(MediaType.APPLICATION_JSON).content("""
                                {"username":"check-account-admin","marketId":%s,"password":"test-password","totpSecret":"JBSWY3DPEHPK3PXP","enabled":true}
                                """.formatted(marketId)))
                .andExpect(status().isOk()).andReturn();
        long connectionId = data(connectionResult).path("id").asLong();
        when(remoteGiftCodeBackendClient.check(any())).thenReturn("连接正常");

        mockMvc.perform(post("/api/v1/redemption-remote-connections/" + connectionId + "/check").session(session)
                        .with(SecurityMockMvcRequestPostProcessors.csrf()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.connected").value(true));
        mockMvc.perform(get("/api/v1/redemption-remote-connections").session(session))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data[?(@.id == " + connectionId + ")].lastCheckedAt").isNotEmpty());
    }

    private JsonNode data(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsString()).path("data");
    }

    private MockHttpSession login() throws Exception {
        return (MockHttpSession) mockMvc.perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"admin\",\"password\":\"admin123\"}"))
                .andExpect(status().isOk()).andReturn().getRequest().getSession(false);
    }
}
