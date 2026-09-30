package com.rajads.erp.importing;

import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;

@RestController
@RequestMapping("/api/v1/imports")
@RequiredArgsConstructor
public class ImportController {
    private final ImportService service;

    @GetMapping
    @PreAuthorize("hasAuthority('IMPORT')")
    public List<ImportDtos.ImportJobResponse> list() { return service.list(); }

    @GetMapping(value = "/template", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('IMPORT')")
    public void template(HttpServletResponse response) throws IOException { writeDownload(response, service.template()); }

    @PostMapping("/paste/preview")
    @PreAuthorize("hasAuthority('IMPORT')")
    public ImportDtos.ImportPreviewResponse previewPaste(@Valid @RequestBody ImportDtos.PastePreviewRequest request) {
        return service.previewPaste(request);
    }

    @PostMapping(value = "/excel/preview", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @PreAuthorize("hasAuthority('IMPORT')")
    public ImportDtos.ImportPreviewResponse previewExcel(@RequestPart("file") MultipartFile file,
                                                         @RequestParam(required = false) Long accountId,
                                                         @RequestParam(required = false) Integer businessYear,
                                                         @RequestParam(required = false) String conflictStrategy) {
        return service.previewExcel(file, accountId, businessYear, conflictStrategy);
    }

    @GetMapping("/{jobId}")
    @PreAuthorize("hasAuthority('IMPORT')")
    public ImportDtos.ImportPreviewResponse get(@PathVariable Long jobId) { return service.get(jobId); }

    @GetMapping("/{jobId}/rows")
    @PreAuthorize("hasAuthority('IMPORT')")
    public List<ImportDtos.ImportRowResponse> rows(@PathVariable Long jobId) { return service.rows(jobId); }

    @GetMapping(value = "/{jobId}/source", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('IMPORT')")
    public void source(@PathVariable Long jobId, HttpServletResponse response) throws IOException {
        writeDownload(response, service.source(jobId));
    }

    @GetMapping(value = "/{jobId}/error-report", produces = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    @PreAuthorize("hasAuthority('IMPORT')")
    public void errorReport(@PathVariable Long jobId, HttpServletResponse response) throws IOException {
        writeDownload(response, service.errorReport(jobId));
    }

    @PostMapping("/{jobId}/commit")
    @PreAuthorize("hasAuthority('IMPORT')")
    public ImportDtos.ImportCommitResponse commit(@PathVariable Long jobId,
                                                   @RequestBody(required = false) ImportDtos.ImportCommitRequest request) {
        return service.commit(jobId, request);
    }

    private void writeDownload(HttpServletResponse response, ImportService.XlsxDownload download) throws IOException {
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setContentLength(download.content().length);
        response.setHeader(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                .filename(download.filename(), StandardCharsets.UTF_8).build().toString());
        response.getOutputStream().write(download.content());
    }
}
