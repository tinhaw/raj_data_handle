package com.rajads.erp.reporting;

import com.rajads.erp.audit.AuditLogRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.io.ByteArrayInputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class ReportExportHttpTest {
    private static final MediaType XLSX = MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");

    @Autowired private MockMvc mockMvc;
    @Autowired private ObjectMapper objectMapper;
    @Autowired private AuditLogRepository auditLogRepository;

    @Test
    void adminCanDownloadRawDailyWorkbookAndExportIsAudited() throws Exception {
        MockHttpSession session = login();
        MvcResult result = mockMvc.perform(get("/api/v1/reports/daily/export")
                        .session(session).param("from", "2099-12-31").param("to", "2099-12-31").param("nominalU", "true"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(XLSX))
                .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION, containsString("daily-report-2099-12-31_to_2099-12-31.xlsx")))
                .andReturn();

        try (XSSFWorkbook workbook = new XSSFWorkbook(new ByteArrayInputStream(result.getResponse().getContentAsByteArray()))) {
            var sheet = workbook.getSheetAt(0);
            var total = sheet.getRow(sheet.getLastRowNum());
            assertThat(total.getCell(0).getStringCellValue()).isEqualTo("合计");
            assertThat(total.getCell(2).getCellFormula()).isNotBlank();
        }
        assertThat(auditLogRepository.findAll()).anySatisfy(log -> {
            assertThat(log.getAction()).isEqualTo("REPORT_EXPORTED");
            assertThat(log.getAfterJson()).contains("\"reportType\":\"DAILY\"");
            assertThat(log.getAfterJson()).doesNotContain("openingBalance");
        });
    }

    private MockHttpSession login() throws Exception {
        MvcResult result = mockMvc.perform(post("/api/v1/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"admin\",\"password\":\"admin123\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.user.permissions").isArray())
                .andReturn();
        JsonNode permissions = objectMapper.readTree(result.getResponse().getContentAsString()).at("/data/user/permissions");
        assertThat(permissions.toString()).contains("REPORT_EXPORT");
        return (MockHttpSession) result.getRequest().getSession(false);
    }
}
