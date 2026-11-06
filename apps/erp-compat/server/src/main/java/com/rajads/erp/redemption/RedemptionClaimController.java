package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.rajads.erp.shared.ApiException;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.io.IOException;

@RestController
@RequestMapping("/api/v1/redemption-campaigns")
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "erp.compatibility", name = "standalone-auth-enabled", havingValue = "false", matchIfMissing = true)
public class RedemptionClaimController {
    private final UnifiedRedemptionClaimClient client;

    @GetMapping("/tasks/{id}/claim-statistics")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public JsonNode statistics(@PathVariable Long id, @RequestParam Map<String, String> query) {
        return client.json("GET", task(id) + "/claim-statistics", query, null);
    }

    @GetMapping("/tasks/{id}/claim-statistics/codes")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public JsonNode codes(@PathVariable Long id, @RequestParam Map<String, String> query) {
        return client.json("GET", task(id) + "/claim-statistics/codes", query, null);
    }

    @GetMapping("/tasks/{id}/claim-records")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public JsonNode records(@PathVariable Long id, @RequestParam Map<String, String> query) {
        return client.json("GET", task(id) + "/claim-records", query, null);
    }

    @GetMapping("/tasks/{id}/claim-statistics/sync-settings")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public JsonNode settings(@PathVariable Long id) {
        return client.json("GET", task(id) + "/claim-statistics/sync-settings", Map.of(), null);
    }

    @PutMapping("/tasks/{id}/claim-statistics/sync-settings")
    @PreAuthorize("hasAuthority('REDEMPTION_STATS_SYNC')")
    public JsonNode save(@PathVariable Long id, @RequestBody JsonNode payload) {
        return client.json("PUT", task(id) + "/claim-statistics/sync-settings", Map.of(), payload);
    }

    @PostMapping("/tasks/{id}/claim-statistics/sync")
    @PreAuthorize("hasAuthority('REDEMPTION_STATS_SYNC')")
    public JsonNode sync(@PathVariable Long id) {
        return client.json("POST", task(id) + "/claim-statistics/sync", Map.of(), null);
    }

    @GetMapping("/claim-statistic-syncs/{id}")
    @PreAuthorize("hasAuthority('REDEMPTION_VIEW')")
    public JsonNode progress(@PathVariable String id) {
        if (!id.matches("[a-zA-Z0-9-]{1,36}")) throw ApiException.badRequest("INVALID_SYNC_ID", "同步任务编号无效");
        return client.json("GET", "/claim-statistic-syncs/" + id, Map.of(), null);
    }

    @GetMapping("/tasks/{id}/claim-statistics/export")
    @PreAuthorize("hasAuthority('REDEMPTION_EXPORT')")
    public void export(@PathVariable Long id, @RequestParam Map<String, String> query,
                       HttpServletResponse response) throws IOException {
        byte[] bytes = client.export(task(id) + "/claim-statistics/export", query);
        response.setHeader("Content-Disposition", "attachment; filename=redemption-claims-" + id + ".xlsx");
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setContentLength(bytes.length);
        response.getOutputStream().write(bytes);
    }

    private String task(Long id) {
        if (id <= 0) throw ApiException.badRequest("INVALID_TASK_ID", "任务编号无效");
        return "/tasks/" + id;
    }
}
