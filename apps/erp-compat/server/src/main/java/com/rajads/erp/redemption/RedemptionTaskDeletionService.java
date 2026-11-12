package com.rajads.erp.redemption;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.rajads.erp.audit.AuditService;
import com.rajads.erp.shared.ApiException;
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import java.time.Instant;
import java.util.*;

/** Each authenticated request advances one item. The browser never supplies the deletion scope. */
@Service @RequiredArgsConstructor
public class RedemptionTaskDeletionService {
 private final RedemptionTaskDeletionRepository jobs;
 private final RedemptionCodeTaskRepository tasks;
 private final RedemptionCodeBatchRepository batches;
 private final RedemptionCodeIssueRepository issues;
 private final RedemptionDeletionService deletions;
 private final EntityManager em;
 private final PlatformTransactionManager tm;
 private final ObjectMapper mapper;
 private final AuditService audit;
 private final RedemptionRemoteDirectory directory;
 public record Scope(Long issueId,Long ownerId,Long marketId,String configurationId){}
 public record Item(Long issueId,String configurationId,String status,String message,
                    RedemptionDeletionService.View plan,List<String> sharedTasks){}
 public record View(Long id,Long rowVersion,Long taskId,String taskNumber,String status,boolean busy,List<Item> items){}
 public record Confirm(Long rowVersion,boolean confirmed,String taskNumber){}
 private record Work(Long jobId,int index,Item item,boolean checking){}
 private TransactionTemplate tx(){return new TransactionTemplate(tm);}

 public View latest(Long taskId){return tx().execute(s->{task(taskId);return jobs.findFirstByTaskIdOrderByIdDesc(taskId).map(this::view).orElse(null);});}
 public View preview(Long taskId){return tx().execute(s->{
  em.refresh(task(taskId),LockModeType.PESSIMISTIC_WRITE);
  var previous=jobs.findFirstByTaskIdOrderByIdDesc(taskId).orElse(null);
  if(previous!=null && (previous.isBusy() || Set.of("CHECKING","RUNNING").contains(previous.getStatus()))) return view(previous);
  if(previous!=null && Set.of("PAUSED","CHECKED").contains(previous.getStatus())) {previous.setStatus("STOPPED");jobs.saveAndFlush(previous);}
  var scope=scope(taskId);var entries=new ArrayList<Item>();var identities=new HashSet<String>();
  for(var target:scope){
   if(!RemoteConfigurationIds.isValid(target.configurationId())){
    entries.add(new Item(target.issueId(),null,"SKIPPED","未登记有效配置 ID，未执行删除",null,List.of()));continue;
   }
   String identity=target.marketId()+":"+target.configurationId();
   if(identities.add(identity)) entries.add(new Item(target.issueId(),target.configurationId(),"WAITING","等待核验",null,List.of()));
  }
  var job=new RedemptionTaskDeletion();job.setTaskId(taskId);job.setStatus("CHECKING");job.setScopeJson(json(scope));job.setItemsJson(json(entries));jobs.saveAndFlush(job);
  audit.record("REDEMPTION_TASK_DELETE_PREVIEW","REDEMPTION_TASK_DELETION",job.getId().toString(),null,null,Map.of("taskId",taskId,"items",entries.size()));
  return view(job);
 });}
 public View confirm(Long taskId,Long jobId,Confirm request){return tx().execute(s->{
  var job=locked(taskId,jobId);
  if(request==null || !request.confirmed() || !Objects.equals(task(taskId).taskNumber(),request.taskNumber()))
   throw ApiException.badRequest("TASK_DELETE_CONFIRMATION_REQUIRED","请输入任务编号，确认删除该任务的全部配置及共享影响");
  if(!"CHECKED".equals(job.getStatus()) || job.isBusy() || !Objects.equals(request.rowVersion(),job.getRowVersion())
      || job.getUpdatedAt().isBefore(Instant.now().minusSeconds(300)) || !job.getScopeJson().equals(json(scope(taskId)))) throw changed();
  if(items(job).stream().noneMatch(i->"CHECKED".equals(i.status()))) throw changed();
  job.setStatus("RUNNING");jobs.saveAndFlush(job);
  audit.record("REDEMPTION_TASK_DELETE_CONFIRMED","REDEMPTION_TASK_DELETION",jobId.toString(),null,null,Map.of("taskId",taskId,"taskNumber",request.taskNumber()));
  return view(job);
 });}
 public View get(Long taskId,Long jobId){return tx().execute(s->view(require(taskId,jobId)));}

 public View next(Long taskId,Long jobId){
  Work work=tx().execute(s->{var job=locked(taskId,jobId);
   if(job.isBusy()) return null;
   boolean checking="CHECKING".equals(job.getStatus());
   if(!checking && !"RUNNING".equals(job.getStatus())) return null;
   if(!checking && !job.getScopeJson().equals(json(scope(taskId)))){job.setStatus("PAUSED");jobs.saveAndFlush(job);return null;}
   var entries=items(job);int index=-1;
   for(int n=0;n<entries.size();n++) if((checking?"WAITING":"CHECKED").equals(entries.get(n).status())) {index=n;break;}
   if(index<0){job.setStatus(checking?"CHECKED":"FINISHED");jobs.saveAndFlush(job);return null;}
   job.setBusy(true);job.setUpdatedAt(Instant.now());jobs.saveAndFlush(job);
   return new Work(jobId,index,entries.get(index),checking);
  });
  if(work==null) return get(taskId,jobId);
  Item result;boolean pause=false;
  try{
   var fresh=deletions.previewForTask(work.item().issueId());
   if(!"CHECKED".equals(fresh.status())){
    result=item(work.item(),fresh,Set.of("DELETED","KEPT").contains(fresh.status())?fresh.status():"UNKNOWN",fresh.message());
    pause=!work.checking() && !Set.of("DELETED","KEPT").contains(fresh.status());
   }else if(work.checking()){
    deletions.requirePermission(fresh);
    result=item(work.item(),fresh,"CHECKED","ABSENT".equals(fresh.remote().path("state").asText())?"已核验不存在；确认后登记主动删除，阻止重建":"可删除");
   }
   else{
    // Batch counters/versions change when a previous configuration is deleted. All target
    // parameters, issue versions, remote fingerprints and shared identities must still match.
    if(!sameApproval(work.item().plan(),fresh)) throw changed();
    var deleted=deletions.confirm(work.item().issueId(),new RedemptionDeletionService.Confirm(fresh.id(),fresh.rowVersion(),true,fresh.configurationId()));
    result=item(work.item(),deleted,"DELETED","ABSENT".equals(fresh.remote().path("state").asText())?"远端原本已不存在，已登记主动删除":"已删除并核验");
   }
  }catch(RuntimeException error){
   var current=deletions.current(work.item().issueId());
   boolean unknown=current!=null && Set.of("DELETING","UNKNOWN").contains(current.status());
   // A permission failure after a successful read must retain that read and its shared scope.
   var retained=current!=null?current:work.item().plan();
   String message=unknown?"删除结果待核对，禁止重发":failureMessage(error,retained);
   result=retained==null?new Item(work.item().issueId(),work.item().configurationId(),unknown?"UNKNOWN":"BLOCKED",
       message,null,work.item().sharedTasks()):item(work.item(),retained,unknown?"UNKNOWN":"BLOCKED",message);
   pause=!work.checking();
  }
  Item completed=result;boolean paused=pause;
  return tx().execute(s->{var job=locked(taskId,jobId);var entries=new ArrayList<>(items(job));entries.set(work.index(),completed);
   job.setItemsJson(json(entries));job.setBusy(false);
   if(paused)job.setStatus("PAUSED");
   else if(entries.stream().noneMatch(i->(work.checking()?"WAITING":"CHECKED").equals(i.status())))
    job.setStatus(work.checking()?"CHECKED":job.getScopeJson().equals(json(scope(taskId)))?"FINISHED":"PAUSED");
   jobs.saveAndFlush(job);return view(job);
  });
 }

 private String failureMessage(RuntimeException failure,RedemptionDeletionService.View plan){
  String identity="";
  if(plan!=null){
   String accountName="ID "+plan.parameters().accountId();
   try {var account=directory.find(plan.parameters().accountId()).orElse(null);if(account!=null)accountName=account.username();}
   catch(RuntimeException ignored){/* A failed directory read must not prevent saving the original failure. */}
   identity=plan.parameters().marketName()+" / 账号 "+accountName+"：";
  }
  if(failure instanceof ApiException api){
   if("DELETE_NOT_AUTHORIZED".equals(api.getCode()) || "DELETE_PERMISSION_REJECTED".equals(api.getCode())
       && api.getMessage().contains("ERP_REDEMPTION_DELETE"))
    return identity+"本系统尚未开启“兑换码永久删除”能力。请由账号管理员在“盘口与远端账号”中授权后重新预检；未提交删除。";
   if("DELETE_PERMISSION_REJECTED".equals(api.getCode()))
    return identity+"删除能力检查未通过："+api.getMessage()+"；未提交删除，请检查账号授权后重新预检。";
   if(api.getStatus().value()==401)return identity+"登录状态已失效，请重新登录后预检；未提交删除。";
   if(api.getStatus().value()==403)return identity+"当前账号没有所需操作权限，请联系管理员检查授权；未提交删除。";
   if("TASK_DELETE_STATE_CHANGED".equals(api.getCode()))return identity+"配置或共享范围已变化，请重新预检并确认；未提交删除。";
   return identity+api.getMessage()+"；本项未提交删除，请重新预检。";
  }
  return identity+"删除前检查暂不可用，请稍后重新预检；本项未提交删除。";
 }

 /** After a lost request, only reconcile an attempted item; never replay its DELETE. */
 public View reconcile(Long taskId,Long jobId){
  var job=tx().execute(s->{var j=locked(taskId,jobId);
   if(j.isBusy() && j.getUpdatedAt().isAfter(Instant.now().minusSeconds(180))) throw ApiException.conflict("TASK_DELETE_RUNNING","当前请求仍在执行，请稍后刷新进度");return view(j);});
  var refreshed=new ArrayList<Item>();
  for(var entry:job.items()){
   var current=entry.configurationId()==null?null:deletions.current(entry.issueId());
   if(current!=null && Set.of("DELETING","UNKNOWN").contains(current.status())){
    try{current=deletions.reconcile(entry.issueId());}catch(RuntimeException ignored){/* Read-only; retain the hold. */}
   }
   refreshed.add(current!=null && "KEPT".equals(current.status())?item(entry,current,"KEPT","已核验并明确保留，旧删除不会重放"):
       current!=null && "DELETED".equals(current.status())?item(entry,current,"DELETED","已核验删除"):
       current!=null && Set.of("DELETING","UNKNOWN").contains(current.status())?item(entry,current,"UNKNOWN","结果待核对，禁止重发"):entry);
  }
  return tx().execute(s->{var current=locked(taskId,jobId);
   if(!Objects.equals(current.getRowVersion(),job.rowVersion())) throw changed();
   current.setBusy(false);current.setStatus("PAUSED");current.setItemsJson(json(refreshed));jobs.saveAndFlush(current);return view(current);});
 }
 private Item item(Item original,RedemptionDeletionService.View plan,String status,String message){
  var shared=tx().execute(s->plan.parameters().sharedBatches().stream().map(b->batches.findById(b.id()).orElseThrow())
      .map(b->task(b.getTaskId()).taskNumber()).distinct().sorted().toList());
  return new Item(original.issueId(),original.configurationId(),status,message,plan,shared);
 }
 private boolean sameApproval(RedemptionDeletionService.View approved,RedemptionDeletionService.View fresh){
  return approved!=null && approved.configurationId().equals(fresh.configurationId())
      && approved.remote().equals(fresh.remote()) && normalized(approved).equals(normalized(fresh));
 }
 private ObjectNode normalized(RedemptionDeletionService.View plan){
  ObjectNode node=mapper.valueToTree(plan.parameters());node.remove("batchVersion");
  node.withArray("sharedBatches").forEach(b->((ObjectNode)b).remove("rowVersion"));return node;
 }
 private List<Scope> scope(Long taskId){
  var ids=batches.findByTaskIdOrderByIdAsc(taskId).stream().map(RedemptionCodeBatch::getId).toList();
  return issues.findByBatchIdInOrderByBatchIdAscClaimDateAscCampaignTierIdAsc(ids).stream().map(i->{var owner=i.configurationOwner();
   return new Scope(i.getId(),owner.getId(),owner.getRemoteMarketId(),owner.getRemoteConfigurationId());}).toList();
 }
 private RedemptionCodeTask task(Long id){return tasks.findById(id).orElseThrow(()->ApiException.notFound("兑换码任务"));}
 private RedemptionTaskDeletion require(Long taskId,Long id){var job=jobs.findById(id).orElseThrow(RedemptionTaskDeletionService::changed);if(!job.getTaskId().equals(taskId))throw changed();return job;}
 private RedemptionTaskDeletion locked(Long taskId,Long id){em.refresh(task(taskId),LockModeType.PESSIMISTIC_WRITE);var j=require(taskId,id);em.refresh(j,LockModeType.PESSIMISTIC_WRITE);return j;}
 private List<Item> items(RedemptionTaskDeletion job){try{return mapper.readValue(job.getItemsJson(),mapper.getTypeFactory().constructCollectionType(List.class,Item.class));}catch(java.io.IOException ex){throw changed();}}
 private View view(RedemptionTaskDeletion job){return new View(job.getId(),job.getRowVersion(),job.getTaskId(),task(job.getTaskId()).taskNumber(),job.getStatus(),job.isBusy(),items(job));}
 private String json(Object value){try{return mapper.writeValueAsString(value);}catch(java.io.IOException ex){throw changed();}}
 private static ApiException changed(){return ApiException.conflict("TASK_DELETE_STATE_CHANGED","任务配置、共享范围或删除确认已变化，请重新预览确认");}
}
