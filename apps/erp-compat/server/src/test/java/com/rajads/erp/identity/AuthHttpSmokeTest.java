package com.rajads.erp.identity;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.web.ServerProperties;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class AuthHttpSmokeTest {
    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ServerProperties serverProperties;

    @Test
    void keepsLoginSessionsAndTheirCookiesForThirtyDays() {
        assertThat(serverProperties.getServlet().getSession().getTimeout()).isEqualTo(Duration.ofDays(30));
        assertThat(serverProperties.getServlet().getSession().getCookie().getMaxAge()).isEqualTo(Duration.ofDays(30));
    }

    @Test
    void loginCreatesSessionAndCsrfEndpointReturnsToken() throws Exception {
        MockHttpSession session = (MockHttpSession) mockMvc.perform(post("/api/v1/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"admin\",\"password\":\"admin123\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.user.username").value("admin"))
                .andReturn().getRequest().getSession(false);

        mockMvc.perform(get("/api/v1/auth/me").session(session))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.username").value("admin"));
        mockMvc.perform(get("/api/v1/auth/csrf"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.token").isNotEmpty());
    }
}
