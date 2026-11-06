package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.shared.ApiResponseAdvice;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.Map;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class RedemptionClaimControllerTest {
    @Test
    void excelBypassesJsonEnvelopeWhileStatisticsUsesNormalApiEnvelope() throws Exception {
        UnifiedRedemptionClaimClient client = mock(UnifiedRedemptionClaimClient.class);
        byte[] excel = new byte[]{80, 75, 3, 4};
        when(client.export("/tasks/1/claim-statistics/export", Map.of())).thenReturn(excel);
        when(client.json("GET", "/tasks/1/claim-statistics", Map.of(), null))
                .thenReturn(new ObjectMapper().readTree("{\"rows\":[]}"));
        var mvc = MockMvcBuilders.standaloneSetup(new RedemptionClaimController(client))
                .setControllerAdvice(new ApiResponseAdvice()).build();
        mvc.perform(get("/api/v1/redemption-campaigns/tasks/1/claim-statistics/export"))
                .andExpect(status().isOk()).andExpect(content().bytes(excel))
                .andExpect(header().string("Content-Disposition", "attachment; filename=redemption-claims-1.xlsx"));
        mvc.perform(get("/api/v1/redemption-campaigns/tasks/1/claim-statistics"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.rows").isArray());
    }
}
