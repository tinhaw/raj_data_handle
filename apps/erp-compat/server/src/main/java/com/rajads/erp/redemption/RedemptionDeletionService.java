package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rajads.erp.audit.AuditService;
import com.rajads.erp.shared.ApiException;
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.Instant;
import java.util.Objects;
import java.util.Set;

/** A tombstone never removes identity, stock, shared references, or automatically recreates a configuration. */
@Service @RequiredArgsConstructor
public class RedemptionDeletionService {
 private final RedemptionCodeIssueRepository issues;
 private final RedemptionCodeBatchRepository batches;
 private final RedemptionDeletionRepository deletions;
 private final RedemptionRecoveryService recovery;
 private final RedemptionBatchProgress progress;
 private final ObjectProvider<UnifiedRedemptionRemoteExecutorClient> executors;
 private final EntityManager em;
 private final PlatformTransactionManager tm;
 private final ObjectMapper mapper;
 private final AuditService audit;
 private final org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate jdbc;
 public record View(Long id, Long rowVersion, String status, String configurationId,
     RedemptionRecoveryService.Snapshot parameters, JsonNode remote, String message, Observation observation) { }
 public record Observation(String state, String checkedAt, String message) { }
 public record Confirm(Long deletionId, Long rowVersion, boolean confirmed, String configurationId) { }
 public record KeepConfirm(Long deletionId,Long rowVersion,boolean confirmed,String configurationId,String fingerprint,boolean previousRequestEnded,String snapshotFingerprint) { }
 private static final String KEEP_ACTION="REDEMPTION_DELETE_KEEP_CONFIRMED";
 private TransactionTemplate tx(){return new TransactionTemplate(tm);}
 public static void requireAvailable(RedemptionCodeIssue issue){
  var state=issue.configurationOwner().getRemoteDeletionState();
  if(state!=null) throw ApiException.conflict("REMOTE_CONFIGURATION_DELETION_HELD",
      "DELETED".equals(state)?"配置已主动删除；历史记录保留，禁止继续发布、下载或自动重建。":"删除结果待核对；禁止发布、下载、修改奖励或重新创建，请只读核对删除结果。");
 }
 public View preview(Long issueId,Long version){return preview(issueId,version,false);}
 View previewForTask(Long issueId){return preview(issueId,null,true);}
 private View preview(Long issueId,Long version,boolean allowAbsent){
  var existing=tx().execute(s->{var i=issue(issueId);return deletions.findByOwnerIssueId(i.configurationOwner().getId()).orElse(null);});
  if(existing!=null && !"CHECKED".equals(existing.getStatus())) return view(existing);
  var snapshot=tx().execute(s->{var target=issue(issueId); requireAvailable(target);
   if(version!=null && !version.equals(target.getRowVersion())) throw changed();
   var owner=target.configurationOwner();
   if(owner.getActiveRecovery()!=null && !Set.of("PRESENT","COMPLETED","MISSING","CHECK_UNAVAILABLE").contains(owner.getActiveRecovery().getStatus())
       || owner.getPolicyUpdate()!=null && !"APPLIED".equals(owner.getPolicyUpdate().getStatus())) throw changed();
   return recovery.policySnapshot(issueId);
  });
  var configurationId=tx().execute(s->issue(snapshot.ownerId()).getRemoteConfigurationId());
  var remote=executor().deletion(snapshot.accountId(),issueId,configurationId,"preview",null);
  boolean absent=allowAbsent && "ABSENT".equals(remote.path("state").asText());
  if(!absent && (!"PRESENT".equals(remote.path("state").asText()) || !remote.path("fingerprint").asText().matches("[a-f0-9]{64}")))
   throw ApiException.conflict("DELETE_CONFIGURATION_NOT_PRESENT","目标配置不可确认存在，未准备删除；请核对缺失配置。");
  return tx().execute(s->{lock(snapshot); if(!snapshot.equals(recovery.policySnapshot(issueId))) throw changed();
   var owner=issue(snapshot.ownerId());
   if(!absent && (owner.getRemoteGroupKey()!=null && !owner.getRemoteGroupKey().equals(remote.path("groupKey").asText())
       || snapshot.code()!=null && !snapshot.code().equalsIgnoreCase(remote.path("giftCode").asText()))) throw changed();
   var d=deletions.findByOwnerIssueId(snapshot.ownerId()).orElseGet(RedemptionDeletion::new);
   if(d.getStatus()!=null && !"CHECKED".equals(d.getStatus())) throw changed();
   d.setOwnerIssueId(snapshot.ownerId());d.setRequestedIssueId(issueId);d.setConfigurationId(configurationId);
   d.setUpdatedAt(Instant.now());d.setStatus("CHECKED");d.setSnapshotJson(json(snapshot));d.setRemoteJson(json(remote));deletions.saveAndFlush(d);
   audit.record("REDEMPTION_DELETE_PREVIEWED","REDEMPTION_DELETION",d.getId().toString(),null,null,
       java.util.Map.of("configurationId",configurationId,"sharedBatches",snapshot.sharedBatches().size()));
   observe(d,"PRESENT".equals(remote.path("state").asText())?"PRESENT":"ABSENT","删除前只读核验");
   return view(d);
  });
 }
 public View confirm(Long issueId,Confirm request){
  if(request==null || !request.confirmed() || request.deletionId()==null || request.rowVersion()==null)
   throw ApiException.badRequest("DELETE_CONFIRMATION_REQUIRED","请核对共享范围及配置 ID，并明确确认永久删除");
  var original=tx().execute(s->{var d=deletions.findById(request.deletionId()).orElseThrow(RedemptionDeletionService::changed);
   owned(d,issueId); if(!Objects.equals(d.getConfigurationId(),request.configurationId())) throw changed();
   if(!"CHECKED".equals(d.getStatus()) || !Objects.equals(d.getRowVersion(),request.rowVersion()) || d.getUpdatedAt().isBefore(Instant.now().minusSeconds(300))) throw changed();
   return view(d);
  });
  // Verify permission before reserving. A rejected permission cannot masquerade as an uncertain write.
  requirePermission(original);
  var reserved=tx().execute(s->{lock(original.parameters());var d=em.find(RedemptionDeletion.class,original.id(),LockModeType.PESSIMISTIC_WRITE);em.refresh(d);
   if(!"CHECKED".equals(d.getStatus()) || !Objects.equals(d.getRowVersion(),request.rowVersion())
       || !original.parameters().equals(recovery.policySnapshot(issueId))) throw changed();
   var owner=issue(d.getOwnerIssueId());owner.setRemoteDeletionState("DELETING");issues.saveAndFlush(owner);
   d.setStatus("DELETING");deletions.saveAndFlush(d);progress.refreshRelated(owner.getId());batches.flush();
   audit.record("REDEMPTION_DELETE_RESERVED","REDEMPTION_DELETION",d.getId().toString(),null,null,java.util.Map.of("configurationId",d.getConfigurationId()));return view(d);
  });
  try{
   // An explicitly confirmed task deletion may tombstone a proven missing configuration.
   // Re-read it; never send DELETE if absence was the approved observation.
   boolean absent="ABSENT".equals(reserved.remote().path("state").asText());
   var result=executor().deletion(reserved.parameters().accountId(),issueId,reserved.configurationId(),
       absent?"preview":"execute",absent?null:reserved.remote().path("fingerprint").asText());
   if(!"ABSENT".equals(result.path("state").asText())) throw changed();
   recordObservation(reserved,"ABSENT","删除后已回读确认原配置不存在");
   return finish(reserved.id(),"DELETED");
  }catch(RuntimeException error){
   String reason=error instanceof ApiException api?api.getMessage():"执行请求或回读核验不可用";
   String code=error instanceof ApiException api?api.getCode():"DELETE_EXECUTION_UNAVAILABLE";
   finish(reserved.id(),"UNKNOWN",java.util.Map.of("reason",reason,"failureCode",code));
   throw ApiException.conflict("REMOTE_DELETE_RESULT_UNCONFIRMED","删除请求结果待核对，进度已保存；只允许回读核对，禁止再次提交删除。原因："+reason);}
 }
 /** A separate explicit KEEP decision never rewinds or replays the original unknown DELETE. */
 public View previewKeep(Long issueId){
  var d=tx().execute(s->{var i=issue(issueId);var row=deletions.findByOwnerIssueId(i.configurationOwner().getId()).orElseThrow(RedemptionDeletionService::changed);owned(row,issueId);return view(row);});
  if("KEPT".equals(d.status()))return d;
  if(!"UNKNOWN".equals(d.status()))throw ApiException.conflict("DELETE_KEEP_NOT_ALLOWED","仅可对结果待核对的旧删除请求明确保留；执行中或已删除配置不能放行。");
  var current=recovery.deletionHoldSnapshot(issueId);
  var old=d.parameters();
  if(!Objects.equals(current.ownerId(),old.ownerId()) || !Objects.equals(current.accountId(),old.accountId())
      || !Objects.equals(current.marketId(),old.marketId()) || !Objects.equals(current.code(),old.code())
      || !current.sharedBatches().stream().map(RedemptionRecoveryService.BatchVersion::id).toList().equals(old.sharedBatches().stream().map(RedemptionRecoveryService.BatchVersion::id).toList()))throw changed();
  var remote=executor().deletion(current.accountId(),issueId,d.configurationId(),"preview",null);
  if(!"PRESENT".equals(remote.path("state").asText()) || !remote.path("fingerprint").asText().equals(d.remote().path("fingerprint").asText())
      || !remote.path("fingerprint").asText().matches("[a-f0-9]{64}"))
   throw ApiException.conflict("DELETE_KEEP_READBACK_MISMATCH","原配置的身份、参数或存在性已变化；仅保留只读核对，未解除删除保护。");
  if(!current.equals(recovery.deletionHoldSnapshot(issueId)))throw changed();
  var proof=remote.deepCopy();((com.fasterxml.jackson.databind.node.ObjectNode)proof).put("keepSnapshotFingerprint",snapshotFingerprint(current));
  return new View(d.id(),d.rowVersion(),d.status(),d.configurationId(),current,proof,"原配置仍存在且与旧确认指纹一致；确认旧请求已结束并决定保留后，才能解除业务阻断。旧删除记录和防重放保护保留。",d.observation());
 }
 public View confirmKeep(Long issueId,KeepConfirm request){
  if(request==null || !request.confirmed() || !request.previousRequestEnded() || request.deletionId()==null || request.rowVersion()==null)
   throw ApiException.badRequest("DELETE_KEEP_CONFIRMATION_REQUIRED","必须确认旧删除请求已结束，并明确决定保留该配置及共享影响。");
  var fresh=previewKeep(issueId);
  if(!Objects.equals(fresh.id(),request.deletionId()) || !Objects.equals(fresh.configurationId(),request.configurationId()))throw changed();
  if("KEPT".equals(fresh.status()))return fresh;
  if(!Objects.equals(fresh.rowVersion(),request.rowVersion()) || !Objects.equals(fresh.remote().path("fingerprint").asText(),request.fingerprint())
      || !Objects.equals(fresh.remote().path("keepSnapshotFingerprint").asText(),request.snapshotFingerprint()))throw changed();
  return tx().execute(s->{lock(fresh.parameters());var d=em.find(RedemptionDeletion.class,fresh.id(),LockModeType.PESSIMISTIC_WRITE);em.refresh(d);
   if(kept(d))return view(d);
   if(!"UNKNOWN".equals(d.getStatus()) || !Objects.equals(d.getRowVersion(),request.rowVersion()))throw changed();
   if(!fresh.parameters().equals(recovery.deletionHoldSnapshot(issueId)))throw changed();
   var owner=issue(d.getOwnerIssueId());em.refresh(owner,LockModeType.PESSIMISTIC_WRITE);
   var related=new java.util.HashSet<>(issues.findRelatedBatchIds(owner.getId()));
   var approved=fresh.parameters().sharedBatches().stream().map(RedemptionRecoveryService.BatchVersion::id).collect(java.util.stream.Collectors.toSet());
   if(!"UNKNOWN".equals(owner.getRemoteDeletionState()) || !Objects.equals(owner.getRemoteConfigurationId(),d.getConfigurationId())
       || !related.equals(approved) || d.getUpdatedAt().isAfter(Instant.now().minusSeconds(180)))throw changed();
   owner.setRemoteDeletionState(null);issues.saveAndFlush(owner);
   audit.record(KEEP_ACTION,"REDEMPTION_DELETION",d.getId().toString(),null,
      java.util.Map.of("originalStatus",d.getStatus(),"remoteAttempted",d.isRemoteAttempted()),
      java.util.Map.of("deletionId",d.getId(),"ownerIssueId",owner.getId(),"configurationId",d.getConfigurationId(),"fingerprint",request.fingerprint(),"previousRequestEnded",true,"sharedBatchIds",approved,"originalDeleteReplayAllowed",false));
   em.flush();progress.refreshRelated(owner.getId());batches.flush();return view(d);
  });
 }
 private String snapshotFingerprint(Object value){try{return java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(json(value).getBytes(java.nio.charset.StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException ex){throw new IllegalStateException(ex);}}
 private boolean kept(RedemptionDeletion d){
  var rows=jdbc.queryForList("select after_json from erp_compat_audit_logs where action=:a and entity_type='REDEMPTION_DELETION' and entity_id=:id order by id desc limit 1",java.util.Map.of("a",KEEP_ACTION,"id",d.getId().toString()));
  if(rows.isEmpty())return false;
  try{var facts=mapper.readTree((String)rows.getFirst().get("after_json"));return facts.path("deletionId").asLong()==d.getId()
      && facts.path("ownerIssueId").asLong()==d.getOwnerIssueId() && facts.path("configurationId").asText().equals(d.getConfigurationId())
      && facts.path("previousRequestEnded").asBoolean() && !facts.path("originalDeleteReplayAllowed").asBoolean(true);}
  catch(java.io.IOException | RuntimeException ignored){return false;}
 }
 public View reconcile(Long issueId){
  var d=tx().execute(s->{var i=issue(issueId);var row=deletions.findByOwnerIssueId(i.configurationOwner().getId()).orElseThrow(RedemptionDeletionService::changed);return view(row);});
  if(Set.of("DELETED","KEPT").contains(d.status())) return d;
  if("CHECKED".equals(d.status())) return preview(issueId,null,true);
  if("DELETING".equals(d.status()) && tx().execute(s->deletions.findById(d.id()).orElseThrow().getUpdatedAt()).isAfter(Instant.now().minusSeconds(120)))
   throw ApiException.conflict("DELETE_STILL_RUNNING","删除请求仍在执行，请稍后只读核对");
  try {
   var result=executor().deletion(d.parameters().accountId(),issueId,d.configurationId(),"preview",null);
   boolean sameId=d.configurationId().equals(result.path("configurationId").asText());
   String state=result.path("state").asText();
   boolean identity=sameId && d.remote().path("fingerprint").asText().matches("[a-f0-9]{64}")
       && d.remote().path("fingerprint").asText().equals(result.path("fingerprint").asText());
   if(sameId && "ABSENT".equals(state)) {
    recordObservation(d,"ABSENT","只读核对确认原配置不存在；不重复删除");
    return finish(d.id(),"DELETED");
   }
   String observed="PRESENT".equals(state)?identity?"PRESENT":"IDENTITY_CHANGED":"UNAVAILABLE";
   recordObservation(d,observed,identity?"原配置仍存在；旧删除请求结果尚未确定，本项暂不重发，可确认继续其他未执行项":
       "IDENTITY_CHANGED".equals(observed)?"配置身份或参数已变化，不能沿用旧删除确认，也不会删除同码的新配置":"远端未提供可靠存在性结果，请稍后只读核对");
   return finish(d.id(),"UNKNOWN");
  } catch(RuntimeException failure) {
   recordObservation(d,"UNAVAILABLE","本次只读核对未完成，不能判断已删除或仍存在；保留原删除记录");
   return finish(d.id(),"UNKNOWN");
  }
 }
 View current(Long issueId){return tx().execute(s->deletions.findByOwnerIssueId(issue(issueId).configurationOwner().getId()).map(this::view).orElse(null));}
 void requirePermission(View plan){executor().deletion(plan.parameters().accountId(),plan.parameters().issueId(),plan.configurationId(),"permission",null);}
 private View finish(Long id,String state){return finish(id,state,java.util.Map.of());}
 private View finish(Long id,String state,java.util.Map<String,String> failure){return tx().execute(s->{var d=em.find(RedemptionDeletion.class,id,LockModeType.PESSIMISTIC_WRITE);em.refresh(d);
  if("DELETED".equals(d.getStatus()) || kept(d)) return view(d);
  var owner=issue(d.getOwnerIssueId());em.refresh(owner,LockModeType.PESSIMISTIC_WRITE);
  d.setStatus(state);owner.setRemoteDeletionState(state);issues.saveAndFlush(owner);deletions.saveAndFlush(d);
  progress.refreshRelated(owner.getId());batches.flush();
  var facts=new java.util.HashMap<String,Object>(failure);facts.put("configurationId",d.getConfigurationId());
  audit.record("REDEMPTION_DELETE_"+state,"REDEMPTION_DELETION",id.toString(),null,null,facts);return view(d);
 });}
 private void lock(RedemptionRecoveryService.Snapshot snapshot){
  for(var b:snapshot.sharedBatches()) em.refresh(batches.findById(b.id()).orElseThrow(RedemptionDeletionService::changed),LockModeType.PESSIMISTIC_WRITE);
  for(Long id:java.util.stream.Stream.of(snapshot.issueId(),snapshot.ownerId()).distinct().sorted().toList()) em.refresh(issue(id),LockModeType.PESSIMISTIC_WRITE);
 }
 private View owned(RedemptionDeletion d,Long issueId){if(!Objects.equals(d.getRequestedIssueId(),issueId))throw changed();return view(d);}
 private View view(RedemptionDeletion d){try{String state=kept(d)?"KEPT":d.getStatus();return new View(d.getId(),d.getRowVersion(),state,d.getConfigurationId(),mapper.readValue(d.getSnapshotJson(),RedemptionRecoveryService.Snapshot.class),mapper.readTree(d.getRemoteJson()),
    "KEPT".equals(state)?"已核验并明确保留配置；原未知删除记录及防重放保护保留，可继续正常业务。":"DELETED".equals(d.getStatus())?"远端配置已删除，原码、库存和共享记录保留；已发布兑换码是否失效需单独核验。":"CHECKED".equals(d.getStatus())?"确认后永久删除远端配置，影响全部共享任务；历史库存保留，不能通过本系统继续使用。":"删除结果待核对；禁止重复提交，请只读核验。",observation(d));}catch(java.io.IOException ex){throw changed();}}
 /** Observations are append-only audit facts; never replace the original approved fingerprint. */
 private void observe(RedemptionDeletion d,String state,String message){
  audit.record("REDEMPTION_DELETE_OBSERVED","REDEMPTION_DELETION",d.getId().toString(),null,null,
      java.util.Map.of("configurationId",d.getConfigurationId(),"state",state,"checkedAt",Instant.now().toString(),"message",message));
 }
 private void recordObservation(View original,String state,String message){tx().executeWithoutResult(s->{
  var d=em.find(RedemptionDeletion.class,original.id(),LockModeType.PESSIMISTIC_WRITE);em.refresh(d);
  if(!Objects.equals(d.getConfigurationId(),original.configurationId()) || "DELETED".equals(d.getStatus()) || kept(d))return;
  observe(d,state,message);
 });}
 private Observation observation(RedemptionDeletion d){
  var rows=jdbc.queryForList("select after_json from erp_compat_audit_logs where action='REDEMPTION_DELETE_OBSERVED' and entity_type='REDEMPTION_DELETION' and entity_id=:id order by id desc limit 1",java.util.Map.of("id",d.getId().toString()));
  if(rows.isEmpty())return null;
  try{var node=mapper.readTree((String)rows.getFirst().get("after_json"));
   if(!d.getConfigurationId().equals(node.path("configurationId").asText()))return null;
   return new Observation(node.path("state").asText(),node.path("checkedAt").asText(),node.path("message").asText());
  }catch(java.io.IOException | RuntimeException ignored){return null;}
 }
 private RedemptionCodeIssue issue(Long id){return issues.findById(id).orElseThrow(RedemptionDeletionService::changed);}
 private UnifiedRedemptionRemoteExecutorClient executor(){var e=executors.getIfAvailable();if(e==null)throw ApiException.conflict("UNIFIED_DELETE_REQUIRED","删除仅支持统一远端账号执行器");return e;}
 private String json(Object value){try{return mapper.writeValueAsString(value);}catch(java.io.IOException ex){throw changed();}}
 private static ApiException changed(){return ApiException.conflict("DELETE_STATE_CHANGED","配置、共享任务或确认状态已变化，请重新核验；未授权重复删除。");}
}
