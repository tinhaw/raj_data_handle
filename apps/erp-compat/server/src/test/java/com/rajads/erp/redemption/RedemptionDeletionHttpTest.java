package com.rajads.erp.redemption;
import com.fasterxml.jackson.databind.*;
import com.rajads.erp.config.RemoteOperationGate;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.*;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.http.MediaType;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(properties="spring.jpa.open-in-view=false") @AutoConfigureMockMvc
class RedemptionDeletionHttpTest {
 @Autowired MockMvc mvc; @Autowired ObjectMapper mapper; @Autowired JdbcTemplate jdbc;
 @MockBean UnifiedRedemptionRemoteExecutorClient executor;
 @MockBean RemoteGiftCodeBackendClient standalone; @MockBean RemoteOperationGate gate;
 private record Fixture(MockHttpSession session,long owner,long alias,long batch,long originalBatch){}
 private Fixture fixture(String suffix) throws Exception {
  var session=login();long market=market(session,"DEL_"+suffix);account(session,market,"del-"+suffix.toLowerCase());
  var original=group(session,market,"DEL_OWNER_"+suffix);var alias=group(session,market,"DEL_ALIAS_"+suffix);
  long owner=original.at("/issues/0/id").asLong(), linked=alias.at("/issues/0/id").asLong();
  jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='3403',remote_reference_id='3403',remote_group_key='group-3403',workflow_status='CODE_IMPORTED',state='GENERATED',redemption_code='0905raj7days0' where id=?",owner);
  jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)",owner,0,market,"0905raj7days0");
  jdbc.update("update erp_compat_redemption_code_issues set reused_from_issue_id=?,workflow_status='CREATED' where id=?",owner,linked);
  when(executor.deletion(anyLong(),anyLong(),eq("3403"),eq("preview"),isNull())).thenReturn(remote("PRESENT"));
  when(executor.deletion(anyLong(),anyLong(),eq("3403"),eq("permission"),isNull())).thenReturn(mapper.readTree("{\"allowed\":true}"));
  when(executor.deletion(anyLong(),anyLong(),eq("3403"),eq("execute"),anyString())).thenAnswer(call->{
   assertThat(org.springframework.transaction.support.TransactionSynchronizationManager.isActualTransactionActive()).isFalse();return remote("ABSENT");});
  return new Fixture(session,owner,linked,alias.at("/batch/id").asLong(),original.at("/batch/id").asLong());
 }
 private JsonNode remote(String state) throws Exception{return mapper.readTree("{\"configurationId\":\"3403\",\"state\":\""+state+"\",\"fingerprint\":\""+"a".repeat(64)+"\",\"groupKey\":\"group-3403\",\"giftCode\":\"0905raj7days0\"}");}
 private String path(Fixture f,String action){return "/api/v1/redemption-campaigns/code-tasks/"+f.alias()+"/deletion/"+action;}
 private org.springframework.test.web.servlet.ResultActions apply(Fixture f,JsonNode preview) throws Exception {
  return mvc.perform(post(path(f,"confirm")).session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
   .content(mapper.writeValueAsString(java.util.Map.of("deletionId",preview.path("id").asLong(),"rowVersion",preview.path("rowVersion").asLong(),"confirmed",true,"configurationId","3403"))));
 }
 private JsonNode unknownForKeep(Fixture f) throws Exception {
  var preview=send(f.session(),path(f,"preview"),"{}");
  when(executor.deletion(any(),any(),any(),eq("execute"),any())).thenThrow(new RuntimeException("synthetic lost response"));
  apply(f,preview).andExpect(status().isConflict());
  jdbc.update("update erp_compat_redemption_deletions set remote_attempted=true,updated_at=? where owner_issue_id=?",java.sql.Timestamp.from(java.time.Instant.now().minusSeconds(300)),f.owner());
  return send(f.session(),path(f,"keep-preview"),"{}");
 }
 private String keepBody(JsonNode p,boolean confirmed,boolean ended) throws Exception {
  return mapper.writeValueAsString(java.util.Map.of("deletionId",p.path("id").asLong(),"rowVersion",p.path("rowVersion").asLong(),"confirmed",confirmed,"previousRequestEnded",ended,"configurationId","3403","fingerprint",p.at("/remote/fingerprint").asText(),"snapshotFingerprint",p.at("/remote/keepSnapshotFingerprint").asText()));
 }
 @Test void explicitKeepPreservesUnknownJournalStockAndPreventsEveryOldDeleteReplay() throws Exception {
  var f=fixture("KEEP");var plan=unknownForKeep(f);
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isEqualTo("UNKNOWN");
  for(boolean ended:java.util.List.of(false,true)) {
   String body=keepBody(plan,ended,ended);
   mvc.perform(post(path(f,"keep-confirm")).session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(body))
      .andExpect(ended?status().isOk():status().isBadRequest());
  }
  assertThat(send(f.session(),path(f,"reconcile"),"{}").path("status").asText()).isEqualTo("KEPT");
  mvc.perform(post(path(f,"keep-confirm")).session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(keepBody(plan,true,true)))
      .andExpect(status().isOk()).andExpect(jsonPath("$.data.status").value("KEPT"));
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isNull();
  assertThat(jdbc.queryForMap("select status,remote_attempted from erp_compat_redemption_deletions where owner_issue_id=?",f.owner()))
      .containsEntry("status","UNKNOWN").containsEntry("remote_attempted",true);
  assertThat(jdbc.queryForObject("select count(*) from erp_compat_audit_logs where action='REDEMPTION_DELETE_KEEP_CONFIRMED'",Integer.class)).isEqualTo(1);
  assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?",Integer.class,f.owner())).isEqualTo(1);
  apply(f,plan).andExpect(status().isConflict());
  verify(executor,times(1)).deletion(any(),any(),any(),eq("execute"),any());
 }
 @Test void keepRejectsAbsentChangedFingerprintAndChangedSharedScope() throws Exception {
  var f=fixture("KEEP_CHANGED");var plan=unknownForKeep(f);
  when(executor.deletion(any(),any(),any(),eq("preview"),isNull())).thenReturn(remote("ABSENT"));
  mvc.perform(post(path(f,"keep-confirm")).session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(keepBody(plan,true,true))).andExpect(status().isConflict());
  var changed=(com.fasterxml.jackson.databind.node.ObjectNode)remote("PRESENT");changed.put("fingerprint","b".repeat(64));
  when(executor.deletion(any(),any(),any(),eq("preview"),isNull())).thenReturn(changed);
  mvc.perform(post(path(f,"keep-confirm")).session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(keepBody(plan,true,true))).andExpect(status().isConflict());
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isEqualTo("UNKNOWN");
  when(executor.deletion(any(),any(),any(),eq("preview"),isNull())).thenReturn(remote("PRESENT"));
  jdbc.update("update erp_compat_redemption_code_batches set row_version=row_version+1 where id=?",f.originalBatch());
  mvc.perform(post(path(f,"keep-confirm")).session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(keepBody(plan,true,true))).andExpect(status().isConflict());
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isEqualTo("UNKNOWN");
  assertThat(jdbc.queryForObject("select count(*) from erp_compat_audit_logs where action='REDEMPTION_DELETE_KEEP_CONFIRMED' and entity_id=?",Integer.class,plan.path("id").asText())).isZero();
 }
 @Test void previewCancelHasNoRemoteWriteAndConfirmedDeleteRetainsSharedStockAndBlocksReuse() throws Exception {
  var f=fixture("SUCCESS");var preview=send(f.session(),path(f,"preview"),"{}");
  assertThat(preview.at("/parameters/sharedBatches").size()).isEqualTo(2);
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isNull();
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
  apply(f,preview).andExpect(status().isOk()).andExpect(jsonPath("$.data.status").value("DELETED"));
  for(long batch:java.util.List.of(f.batch(),f.originalBatch())){
   mvc.perform(get("/api/v1/redemption-campaigns/batches/"+batch).session(f.session())).andExpect(jsonPath("$.data.issues[0].workflowStatus").value("REMOTE_DELETED")).andExpect(jsonPath("$.data.batch.importedCount").value(0));
   mvc.perform(get("/api/v1/redemption-campaigns/batches/"+batch+"/export").session(f.session())).andExpect(status().isConflict());
  }
  assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id=?",Integer.class,f.owner())).isEqualTo(1);
  mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+f.alias()+"/remote-download").session(f.session()).with(csrf())).andExpect(status().isConflict());
  mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+f.alias()+"/remote-create").session(f.session()).with(csrf())).andExpect(status().isConflict());
  mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+f.alias()+"/recovery-check").session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{}")).andExpect(status().isConflict());
  apply(f,preview).andExpect(status().isConflict());
  verify(executor,times(1)).deletion(any(),any(),any(),eq("execute"),any());
 }
 @Test void unknownWriteOnlyReconcilesReadOnlyAndNeverReplays() throws Exception {
  var f=fixture("UNKNOWN");var preview=send(f.session(),path(f,"preview"),"{}");
  when(executor.deletion(any(),any(),any(),eq("execute"),any())).thenThrow(new RuntimeException("synthetic unknown"));
  apply(f,preview).andExpect(status().isConflict());apply(f,preview).andExpect(status().isConflict());
  send(f.session(),path(f,"reconcile"),"{}");
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isEqualTo("UNKNOWN");
  when(executor.deletion(any(),any(),any(),eq("preview"),isNull())).thenReturn(remote("ABSENT"));
  assertThat(send(f.session(),path(f,"reconcile"),"{}").path("status").asText()).isEqualTo("DELETED");
  verify(executor,times(1)).deletion(any(),any(),any(),eq("execute"),any());
 }
 @Test void staleSharedSnapshotCannotDelete() throws Exception {
  var f=fixture("STALE");var preview=send(f.session(),path(f,"preview"),"{}");
  jdbc.update("update erp_compat_redemption_code_batches set row_version=row_version+1 where id=?",f.originalBatch());
  apply(f,preview).andExpect(status().isConflict());verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
 }
 @Test void permissionDenialDoesNotReserveUnknownDeletion() throws Exception {
  var f=fixture("DENIED");var preview=send(f.session(),path(f,"preview"),"{}");
  when(executor.deletion(any(),any(),any(),eq("permission"),isNull())).thenThrow(com.rajads.erp.shared.ApiException.conflict("NOT_AUTHORIZED","synthetic denied"));
  apply(f,preview).andExpect(status().isConflict());
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isNull();
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
 }
 @Test void identicalConfigurationIdsAcrossMarketsAreBothIncluded() throws Exception {
  var a=fixture("MARKET_A");var b=fixture("MARKET_B");
  jdbc.update("update erp_compat_redemption_code_batches set task_id=? where id=?",taskId(a),b.batch());
  var plan=bulkPreview(a);assertThat(plan.path("items").size()).isEqualTo(2);
  plan=bulkConfirm(a,plan);plan=bulkNext(a,plan);plan=bulkNext(a,plan);
  assertThat(plan.path("status").asText()).isEqualTo("FINISHED");
  verify(executor,times(2)).deletion(any(),any(),eq("3403"),eq("execute"),any());
 }
 @Test void permissionIsCheckedDuringTaskPreviewAndDoesNotReserveDeletion() throws Exception {
  var f=multiFixture("DENIED");
  when(executor.deletion(any(),any(),any(),eq("permission"),isNull())).thenThrow(com.rajads.erp.shared.ApiException.conflict("DELETE_PERMISSION_REJECTED","远端账号未获得 ERP_REDEMPTION_DELETE 能力授权。"));
  var plan=bulkPreview(f);for(var item:plan.path("items")){
   assertThat(item.path("status").asText()).isEqualTo("BLOCKED");
   assertThat(item.path("message").asText()).contains("bulk-denied","兑换码永久删除","盘口与远端账号","未提交删除");
   assertThat(item.at("/plan/parameters/claimDate").asText()).isNotBlank();
   assertThat(item.at("/plan/parameters/marketName").asText()).isNotBlank();
   assertThat(item.at("/plan/remote/giftCode").asText()).startsWith("090");
   assertThat(item.path("sharedTasks").size()).isEqualTo(2);
  }
  mvc.perform(post(bulkPath(f)+"/"+plan.path("id").asLong()+"/confirm").session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
    .content(mapper.writeValueAsString(java.util.Map.of("rowVersion",plan.path("rowVersion").asLong(),"taskNumber",plan.path("taskNumber").asText(),"confirmed",true)))).andExpect(status().isConflict());
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isNull();
  // Opening capability and re-previewing prepares confirmation; it still cannot execute on its own.
  when(executor.deletion(any(),any(),any(),eq("permission"),isNull())).thenReturn(mapper.readTree("{\"allowed\":true}"));
  plan=bulkPreview(f);for(var item:plan.path("items"))assertThat(item.path("status").asText()).isEqualTo("CHECKED");
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
 }

 @Test void preflightReadFailureIsBlockedWithoutInferringAnUnknownWrite() throws Exception {
  var f=multiFixture("READ_DOWN");
  when(executor.deletion(any(),any(),any(),eq("preview"),isNull())).thenThrow(new com.rajads.erp.identity.CompatibilityIdentityUnavailableException("synthetic unavailable"));
  var plan=bulkPreview(f);for(var item:plan.path("items")){
   assertThat(item.path("status").asText()).isEqualTo("BLOCKED");
   assertThat(item.path("message").asText()).contains("检查暂不可用","未提交删除").doesNotContain("结果待核对");
  }
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
 }
 @Test void configurationScopeChangesAfterConfirmationPauseAllFurtherDeletes() throws Exception {
  var f=multiFixture("LATE_SCOPE");var plan=bulkConfirm(f,bulkPreview(f));
  jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='9999' where id=?",f.owner());
  plan=bulkNext(f,plan);assertThat(plan.path("status").asText()).isEqualTo("PAUSED");
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
 }
 private Fixture multiFixture(String suffix) throws Exception {
  var session=login();long market=market(session,"BULK_"+suffix);account(session,market,"bulk-"+suffix.toLowerCase());
  var original=group(session,market,"BULK_OWNER_"+suffix,1,true);var alias=group(session,market,"BULK_ALIAS_"+suffix,1,true);
  for(int n=0;n<2;n++){
   long owner=original.at("/issues/"+n+"/id").asLong(), linked=alias.at("/issues/"+n+"/id").asLong();
   String id=""+(3403+n), code="090"+(5+n)+"raj7days0";
   jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id=?,remote_reference_id=?,remote_group_key=?,workflow_status='CODE_IMPORTED',state='GENERATED',redemption_code=? where id=?",id,id,"group-"+id,code,owner);
   jdbc.update("insert into erp_compat_redemption_issue_codes(issue_id,code_index,remote_market_id,code) values(?,?,?,?)",owner,0,market,code);
   jdbc.update("update erp_compat_redemption_code_issues set reused_from_issue_id=?,workflow_status='CREATED' where id=?",owner,linked);
  }
  when(executor.deletion(any(),any(),any(),eq("permission"),isNull())).thenReturn(mapper.readTree("{\"allowed\":true}"));
  when(executor.deletion(any(),any(),any(),eq("preview"),isNull())).thenAnswer(c->bulkRemote(c.getArgument(2),"PRESENT","a"));
  when(executor.deletion(any(),any(),any(),eq("execute"),any())).thenAnswer(c->bulkRemote(c.getArgument(2),"ABSENT","a"));
  return new Fixture(session,original.at("/issues/0/id").asLong(),alias.at("/issues/0/id").asLong(),alias.at("/batch/id").asLong(),original.at("/batch/id").asLong());
 }
 private JsonNode bulkRemote(String id,String state,String fingerprint) throws Exception {
  var node=mapper.createObjectNode();node.put("configurationId",id);node.put("state",state);node.put("fingerprint",fingerprint.repeat(64));
  node.put("groupKey","group-"+id);node.put("giftCode","3403".equals(id)?"0905raj7days0":"0906raj7days0");return node;
 }
 private long taskId(Fixture f){return jdbc.queryForObject("select task_id from erp_compat_redemption_code_batches where id=?",Long.class,f.batch());}
 private String bulkPath(Fixture f){return "/api/v1/redemption-campaigns/tasks/"+taskId(f)+"/deletion";}
 private JsonNode bulkPreview(Fixture f) throws Exception {
  var plan=send(f.session(),bulkPath(f)+"/preview","{}");int count=0;
  while("CHECKING".equals(plan.path("status").asText()) && count++<10) plan=send(f.session(),bulkPath(f)+"/"+plan.path("id").asLong()+"/next","{}");
  assertThat(plan.path("status").asText()).isEqualTo("CHECKED");return plan;
 }
 private JsonNode bulkConfirm(Fixture f,JsonNode plan) throws Exception {
  return send(f.session(),bulkPath(f)+"/"+plan.path("id").asLong()+"/confirm",mapper.writeValueAsString(java.util.Map.of("rowVersion",plan.path("rowVersion").asLong(),"taskNumber",plan.path("taskNumber").asText(),"confirmed",true)));
 }
 private JsonNode bulkNext(Fixture f,JsonNode plan) throws Exception {return send(f.session(),bulkPath(f)+"/"+plan.path("id").asLong()+"/next","{}");}
 @Test void taskDeletionDeduplicatesSharedOwnersAndDeletesAllItemsDespiteBatchVersionChanges() throws Exception {
  var f=multiFixture("ALL");
  // Include the original and its alias in this same visible task: one remote identity per date.
  jdbc.update("update erp_compat_redemption_code_batches set task_id=? where id=?",taskId(f),f.originalBatch());
  var plan=bulkPreview(f);assertThat(plan.path("items").size()).isEqualTo(2);
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
  plan=bulkConfirm(f,plan);plan=bulkNext(f,plan);plan=bulkNext(f,plan);
  assertThat(plan.path("status").asText()).isEqualTo("FINISHED");
  for(var item:plan.path("items")) assertThat(item.path("status").asText()).isEqualTo("DELETED");
  bulkNext(f,plan);verify(executor,times(2)).deletion(any(),any(),any(),eq("execute"),any());
  assertThat(jdbc.queryForObject("select count(*) from erp_compat_redemption_issue_codes where issue_id in (select id from erp_compat_redemption_code_issues where batch_id=?)",Integer.class,f.originalBatch())).isEqualTo(2);
  mvc.perform(post(bulkPath(f)+"/"+plan.path("id").asLong()+"/confirm").session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{\"confirmed\":true}")).andExpect(status().isBadRequest());
 }
 @Test void taskDeletionRequiresTaskNumberAndFrozenScopeAndDoesNotWriteOnCancel() throws Exception {
  var f=multiFixture("SCOPE");var plan=bulkPreview(f);
  assertThat(plan.at("/items/0/sharedTasks").size()).isEqualTo(2);
  mvc.perform(post(bulkPath(f)+"/"+plan.path("id").asLong()+"/confirm").session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
    .content(mapper.writeValueAsString(java.util.Map.of("rowVersion",plan.path("rowVersion").asLong(),"taskNumber","wrong","confirmed",true)))).andExpect(status().isBadRequest());
  jdbc.update("update erp_compat_redemption_code_issues set remote_configuration_id='9999' where id=?",f.owner());
  mvc.perform(post(bulkPath(f)+"/"+plan.path("id").asLong()+"/confirm").session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON)
    .content(mapper.writeValueAsString(java.util.Map.of("rowVersion",plan.path("rowVersion").asLong(),"taskNumber",plan.path("taskNumber").asText(),"confirmed",true)))).andExpect(status().isConflict());
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
 }
 @Test void changedRemoteFingerprintPausesWithoutDeleting() throws Exception {
  var f=multiFixture("CHANGED");var plan=bulkConfirm(f,bulkPreview(f));
  when(executor.deletion(any(),any(),eq("3403"),eq("preview"),isNull())).thenReturn(bulkRemote("3403","PRESENT","b"));
  plan=bulkNext(f,plan);assertThat(plan.path("status").asText()).isEqualTo("PAUSED");
  assertThat(plan.at("/items/0/status").asText()).isEqualTo("BLOCKED");
  verify(executor,never()).deletion(any(),any(),any(),eq("execute"),any());
 }
 @Test void uncertainTaskDeletePausesAndReconciliationNeverResubmits() throws Exception {
  var f=multiFixture("UNKNOWN");var plan=bulkConfirm(f,bulkPreview(f));
  when(executor.deletion(any(),any(),eq("3403"),eq("execute"),any())).thenThrow(new RuntimeException("synthetic timeout"));
  plan=bulkNext(f,plan);assertThat(plan.path("status").asText()).isEqualTo("PAUSED");
  assertThat(plan.at("/items/0/status").asText()).isEqualTo("UNKNOWN");bulkNext(f,plan);
  send(f.session(),bulkPath(f)+"/"+plan.path("id").asLong()+"/reconcile","{}");
  verify(executor,times(1)).deletion(any(),any(),any(),eq("execute"),any());
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isEqualTo("UNKNOWN");
 }
 @Test void provenAbsentTaskConfigurationIsTombstonedWithoutDeleteAndCannotRebuild() throws Exception {
  var f=multiFixture("ABSENT");
  when(executor.deletion(any(),any(),eq("3403"),eq("preview"),isNull())).thenReturn(bulkRemote("3403","ABSENT","a"));
  var plan=bulkConfirm(f,bulkPreview(f));plan=bulkNext(f,plan);plan=bulkNext(f,plan);
  assertThat(plan.path("status").asText()).isEqualTo("FINISHED");
  assertThat(plan.at("/items/0/message").asText()).contains("原本已不存在");
  verify(executor,never()).deletion(any(),any(),eq("3403"),eq("execute"),any());
  verify(executor,times(1)).deletion(any(),any(),eq("3404"),eq("execute"),any());
  assertThat(jdbc.queryForObject("select remote_deletion_state from erp_compat_redemption_code_issues where id=?",String.class,f.owner())).isEqualTo("DELETED");
  mvc.perform(post(path(f,"reconcile")).session(f.session()).with(csrf())).andExpect(status().isOk());
  mvc.perform(post("/api/v1/redemption-campaigns/code-tasks/"+f.alias()+"/recovery-check").session(f.session()).with(csrf()).contentType(MediaType.APPLICATION_JSON).content("{}")).andExpect(status().isConflict());
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
        return group(session, market, code, 1);
    }

    private JsonNode group(MockHttpSession session, long market, String code, int keyNumber) throws Exception {
        return group(session,market,code,keyNumber,false);
    }

    private JsonNode group(MockHttpSession session, long market, String code, int keyNumber, boolean twoDays) throws Exception {
        return send(session, "/api/v1/redemption-campaigns/groups", """
                {"code":"%s","name":"%s","claimDateFrom":"2026-09-05","claimDateTo":"2026-09-05","lookbackDays":7,
                 "tiers":[{"displayName":"全部用户","minDepositAmount":0,"bonusAmount":1,"bonusMaxAmount":3,"sortOrder":1}],
                 "remoteMarketId":%s,"redemptionType":"%s","tierUserTypes":["ALL_USERS"],"tierLabelIds":[[]],
                 "remoteOptions":{"publishEnvironment":"test","flowTimes":5,"creationIntervalSeconds":5,"keyNumber":%d,"singleUserLimit":1,"singleKeyLimit":3000,"requireBindBankCard":false,"requireBindPhone":true,"checkUuid":true,"uuidRewardLimit":1,"checkLoginIp":true,"loginIpRewardLimit":1,"checkRegisterIp":true,"registerIpRewardLimit":1}}
                """.formatted(code, code, market, keyNumber == 1 ? "SEVEN_DAY_DEPOSIT" : "AGENT", keyNumber).replace("\"claimDateTo\":\"2026-09-05\"",twoDays?"\"claimDateTo\":\"2026-09-06\"":"\"claimDateTo\":\"2026-09-05\""));
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
