package com.rajads.erp.identity;

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

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class SessionSecurityHttpTest {
    @Autowired private MockMvc mockMvc;
    @Autowired private ObjectMapper objectMapper;

    @Test
    void disabledUserCannotLoginAndExistingSessionIsRejectedOnItsNextRequest() throws Exception {
        MockHttpSession admin = login("admin", "admin123");
        User user = createDataEntryUser(admin);
        MockHttpSession memberSession = login(user.username(), "password123");

        csrfJson(patch("/api/v1/users/" + user.id()), "{\"enabled\":false,\"rowVersion\":" + user.rowVersion() + "}", admin)
                .andExpect(status().isOk());

        mockMvc.perform(get("/api/v1/auth/me").session(memberSession)).andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + user.username() + "\",\"password\":\"password123\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("AUTHENTICATION_FAILED"));
    }

    @Test
    void roleChangeTakesEffectForAnExistingSessionWithoutLoggingInAgain() throws Exception {
        MockHttpSession admin = login("admin", "admin123");
        User user = createDataEntryUser(admin);
        MockHttpSession memberSession = login(user.username(), "password123");

        mockMvc.perform(get("/api/v1/imports").session(memberSession)).andExpect(status().isOk());
        mockMvc.perform(get("/api/v1/period-locks").session(memberSession).param("month", "2026-07-01"))
                .andExpect(status().isOk());
        csrfJson(put("/api/v1/users/" + user.id() + "/roles"), "{\"roleCodes\":[\"AUDITOR\"]}", admin)
                .andExpect(status().isOk());

        mockMvc.perform(get("/api/v1/imports").session(memberSession)).andExpect(status().isForbidden());
    }

    private User createDataEntryUser(MockHttpSession admin) throws Exception {
        String username = "session-" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        MvcResult result = csrfJson(post("/api/v1/users"), "{\"username\":\"" + username + "\",\"password\":\"password123\","
                        + "\"displayName\":\"Session Test\",\"roleCodes\":[\"DATA_ENTRY\"],\"allOperators\":false,\"operatorIds\":[]}", admin)
                .andExpect(status().isOk()).andReturn();
        JsonNode data = objectMapper.readTree(result.getResponse().getContentAsString()).at("/data");
        return new User(data.path("id").asLong(), data.path("username").asText(), data.path("rowVersion").asLong());
    }

    private MockHttpSession login(String username, String password) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"" + username + "\",\"password\":\"" + password + "\"}"))
                .andExpect(status().isOk()).andReturn();
        MockHttpSession session = (MockHttpSession) result.getRequest().getSession(false);
        assertThat(session).isNotNull();
        return session;
    }

    private org.springframework.test.web.servlet.ResultActions csrfJson(org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder request,
                                                                          String body, MockHttpSession session) throws Exception {
        return mockMvc.perform(request.session(session).with(SecurityMockMvcRequestPostProcessors.csrf())
                .contentType(MediaType.APPLICATION_JSON).content(body));
    }

    private record User(long id, String username, long rowVersion) { }
}
