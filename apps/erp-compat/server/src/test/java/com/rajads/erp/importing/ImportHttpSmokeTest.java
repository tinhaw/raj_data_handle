package com.rajads.erp.importing;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class ImportHttpSmokeTest {
    @Autowired private MockMvc mockMvc;
    @Autowired private ObjectMapper objectMapper;

    @Test
    void standardTabPastePreviewsAndCommitsAtomically() throws Exception {
        MockHttpSession session = login();
        long operatorId = id(postJson("/api/v1/operators", "{\"code\":\"AA\",\"name\":\"AA\"}", session));
        long accountId = id(postJson("/api/v1/operators/" + operatorId + "/accounts",
                "{\"code\":\"USDT\",\"name\":\"AA USDT\",\"asset\":\"USDT\"}", session));
        String tab = "日期\t昨日结余\t转U\t消耗\n2026-07-01\t100\t1000\t900";
        MvcResult preview = postJson("/api/v1/imports/paste/preview",
                "{\"accountId\":" + accountId + ",\"text\":" + objectMapper.writeValueAsString(tab) + "}", session)
                .andExpect(jsonPath("$.data.job.validRows").value(1))
                .andReturn();
        long jobId = objectMapper.readTree(preview.getResponse().getContentAsString()).at("/data/job/id").asLong();
        MvcResult history = mockMvc.perform(get("/api/v1/imports").session(session)).andExpect(status().isOk()).andReturn();
        JsonNode historyRows = objectMapper.readTree(history.getResponse().getContentAsString()).at("/data");
        assertThat(historyRows.toString()).contains("\"id\":" + jobId).contains("\"createdBy\"");
        postJson("/api/v1/imports/" + jobId + "/commit", "{}", session)
                .andExpect(jsonPath("$.data.created").value(1));
    }

    private MockHttpSession login() throws Exception {
        return (MockHttpSession) mockMvc.perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"admin\",\"password\":\"admin123\"}"))
                .andExpect(status().isOk()).andReturn().getRequest().getSession(false);
    }

    private org.springframework.test.web.servlet.ResultActions postJson(String path, String content, MockHttpSession session) throws Exception {
        return mockMvc.perform(post(path).session(session).with(SecurityMockMvcRequestPostProcessors.csrf())
                .contentType(MediaType.APPLICATION_JSON).content(content)).andExpect(status().isOk());
    }
    private long id(org.springframework.test.web.servlet.ResultActions result) throws Exception {
        JsonNode json = objectMapper.readTree(result.andReturn().getResponse().getContentAsString());
        long id = json.at("/data/id").asLong(); assertThat(id).isPositive(); return id;
    }
}
