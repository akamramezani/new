package ai.medconsults.derm

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import ai.medconsults.derm.engine.*
import java.util.Locale

class MainActivity : ComponentActivity() {
 override fun onCreate(savedInstanceState:Bundle?) {
  super.onCreate(savedInstanceState)
  val catalog=PresentationCatalog(assets); val engine=OfflineScalyEngine(assets)
  setContent { MaterialTheme { DermatologyHome(catalog,engine) } }
 }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DermatologyHome(catalog:PresentationCatalog,engine:OfflineScalyEngine) {
 val ids=remember{catalog.presentationIds}
 var selectedId by remember{mutableStateOf("scaly")}
 var menu by remember{mutableStateOf(false)}
 var data by remember{mutableStateOf<PresentationData?>(null)}
 var error by remember{mutableStateOf<String?>(null)}
 val answers=remember(selectedId){mutableStateMapOf<Int,Boolean>()}
 var result by remember(selectedId){mutableStateOf<ScalyResult?>(null)}
 var scoreError by remember(selectedId){mutableStateOf<String?>(null)}
 var selectedDx by remember(selectedId){mutableStateOf<String?>(null)}
 var selectedTest by remember(selectedId){mutableStateOf<Int?>(null)}
 var showContext by remember(selectedId){mutableStateOf(false)}
 LaunchedEffect(selectedId){try{data=catalog.load(selectedId);error=null}catch(e:Exception){data=null;error=e.message}}
 Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)){
  Text("MedConsults",style=MaterialTheme.typography.headlineMedium)
  Text("Dermatology Differential Engine",style=MaterialTheme.typography.titleLarge)
  Text("Shortlist · Discriminate · Confirm",style=MaterialTheme.typography.bodyLarge)
  Text("Offline knowledge · ${ids.size} presentations",style=MaterialTheme.typography.labelMedium)
  HorizontalDivider()
  ExposedDropdownMenuBox(expanded=menu,onExpandedChange={menu=!menu}){
   OutlinedTextField(value=data?.label?:selectedId,onValueChange={},readOnly=true,label={Text("Clinical presentation")},trailingIcon={ExposedDropdownMenuDefaults.TrailingIcon(menu)},modifier=Modifier.menuAnchor().fillMaxWidth())
   ExposedDropdownMenu(expanded=menu,onDismissRequest={menu=false}){ids.forEach{id->DropdownMenuItem(text={Text(runCatching{catalog.load(id).label}.getOrDefault(id))},onClick={selectedId=id;menu=false})}}
  }
  error?.let{Text(it,color=MaterialTheme.colorScheme.error)}
  data?.let{p->
   Text(p.group.uppercase(Locale.US),style=MaterialTheme.typography.labelLarge)
   Text(p.label,style=MaterialTheme.typography.headlineSmall)
   if(p.question.isNotBlank())Text(p.question,style=MaterialTheme.typography.titleMedium)
   if(p.lead.isNotBlank())Text(p.lead)
   Card(colors=CardDefaults.cardColors(containerColor=MaterialTheme.colorScheme.errorContainer)){
    Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(8.dp)){
     Text("Safety and escalation",style=MaterialTheme.typography.titleMedium)
     Text(p.safetyFlag)
     p.stopRules.forEachIndexed{i,r->Column(verticalArrangement=Arrangement.spacedBy(3.dp)){Text("${i+1}. ${r.label}",style=MaterialTheme.typography.titleSmall);Text(r.action,style=MaterialTheme.typography.bodyMedium)}}
     Text("These are reference warnings, not automated triage. Assess urgency clinically.",style=MaterialTheme.typography.labelSmall)
    }
   }
   Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)){
    AssistChip(onClick={showContext=!showContext},label={Text("Context modifiers (${p.contexts.size})")})
    AssistChip(onClick={selectedTest=null},label={Text("Tests (${p.tests.size})")})
   }
   if(showContext){
    Text("Patient context reference",style=MaterialTheme.typography.titleLarge)
    Text("The source package supplies these multipliers. This build displays them but does not apply them to probabilities.")
    p.contexts.forEach{c->Card{Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(4.dp)){
     Text(c.label,style=MaterialTheme.typography.titleSmall)
     c.ageRange?.let{Text("Age range encoded: ${it.first}–${it.second}")}
     Text(c.multipliers.entries.joinToString(" · "){ "${it.key}: ×${fmt(it.value)}" })
     Text("Evidence: ${c.grade} · ${c.source}",style=MaterialTheme.typography.labelSmall)
    }}}
   }
   Text("Clinical findings",style=MaterialTheme.typography.titleLarge)
   Text("Record only findings you have actually assessed. Unanswered items remain unknown.")
   p.findings.forEach{f->
    Card { Column(Modifier.fillMaxWidth().padding(12.dp),verticalArrangement=Arrangement.spacedBy(5.dp)){
     Text("${f.index+1}. ${f.label}",style=MaterialTheme.typography.bodyLarge)
     Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){
      FilterChip(selected=answers[f.index]==true,onClick={answers[f.index]=true;result=null},label={Text("Yes")})
      FilterChip(selected=answers[f.index]==false,onClick={answers[f.index]=false;result=null},label={Text("No")})
      if(f.index in answers)TextButton(onClick={answers.remove(f.index);result=null}){Text("Clear")}
     }
     Text("Finding group: ${f.group} · Evidence: ${f.grade} · ${f.source}",style=MaterialTheme.typography.labelSmall)
     if(f.likelihoods.isNotEmpty())Text("Encoded likelihood factors (yes / no): "+f.likelihoods.entries.joinToString(" · "){"${it.key}: ${fmt(it.value.first)} / ${fmt(it.value.second)}"},style=MaterialTheme.typography.bodySmall)
    }}
   }
   if(p.id=="scaly"){
    Button(onClick={try{result=engine.score(answers.toMap());scoreError=null}catch(e:Exception){result=null;scoreError=e.message}},enabled=answers.isNotEmpty(),modifier=Modifier.fillMaxWidth()){Text("Calculate provisional scaly ranking")}
    scoreError?.let{Text(it,color=MaterialTheme.colorScheme.error)}
    result?.let{o->
     Text("Provisional ranking (not parity-validated)",style=MaterialTheme.typography.titleLarge)
     Text("Answered: ${o.answeredCount} · Scored: ${o.scoredCount} · Residual: ${fmt(o.residual)}")
     o.ranked.forEachIndexed{i,d->ListItem(headlineContent={Text("${i+1}. ${d.name}")},supportingContent={Text("Model weight: ${fmt(d.weight)}")},trailingContent={Text("${fmt(d.probability*100)}%")})}
     if(o.dropped.isNotEmpty())Text("Correlated findings omitted: "+o.dropped.joinToString{it.label})
    }
   }else{
    Card(colors=CardDefaults.cardColors(containerColor=MaterialTheme.colorScheme.surfaceVariant)){
     Column(Modifier.padding(12.dp)){Text("Scoring not yet enabled for this presentation",style=MaterialTheme.typography.titleMedium);Text("The source knowledge is available, but a verified scoring implementation and production parity test vectors are still required. No invented probability ranking is shown.")}
    }
   }
   HorizontalDivider()
   Text("Differential diagnoses (${p.diagnoses.size})",style=MaterialTheme.typography.titleLarge)
   Text("Select a diagnosis to open its full offline clinical profile.")
   p.diagnoses.forEach{d->
    Card(Modifier.fillMaxWidth().clickable{selectedDx=if(selectedDx==d.id)null else d.id}){
     Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(5.dp)){
      Text(d.name,style=MaterialTheme.typography.titleMedium)
      Text("Evidence grade: ${d.grade} · Source: ${d.source}",style=MaterialTheme.typography.labelSmall)
      if(d.baseWeight!=null)Text("Source base weight: ${fmt(d.baseWeight)}",style=MaterialTheme.typography.labelSmall)
      if(selectedDx==d.id){
       ProfileSection("Typical presentation",d.look)
       ProfileSection("Features supporting diagnosis",d.supporting.joinToString("\n• ","• "))
       ProfileSection("Features arguing against",d.opposing.joinToString("\n• ","• "))
       ProfileSection("Clinical features / confirmation",d.clinicalFeatures)
       ProfileSection("Dermoscopy",d.dermoscopy)
       ProfileSection("Histopathology",d.histopathology)
       ProfileSection("Associations",d.associations)
       ProfileSection("Management reference",d.management)
       if(d.locations.isNotEmpty())ProfileSection("Typical sites",d.locations.joinToString(", "))
       ProfileSection("Distribution pattern",d.pattern)
      }
     }
    }
   }
   HorizontalDivider()
   Text("Diagnostic tests and confirmation (${p.tests.size})",style=MaterialTheme.typography.titleLarge)
   p.tests.forEach{t->
    Card(Modifier.fillMaxWidth().clickable{selectedTest=if(selectedTest==t.index)null else t.index}){
     Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(5.dp)){
      Text(t.label,style=MaterialTheme.typography.titleMedium)
      Text("Target: ${t.target} · Evidence: ${t.grade} · ${t.source}",style=MaterialTheme.typography.labelSmall)
      if(t.sensitivity!=null||t.specificity!=null)Text("Sensitivity: ${t.sensitivity?.let{fmt(it)}?:"—"}% · Specificity: ${t.specificity?.let{fmt(it)}?:"—"}%")
      if(selectedTest==t.index){
       ProfileSection("When to use",t.whenToUse)
       ProfileSection("Positive result",t.positive)
       ProfileSection("Negative result",t.negative)
       ProfileSection("Limitations / sampling",t.caveat)
      }
     }
    }
   }
   Text("Package audit",style=MaterialTheme.typography.titleMedium)
   Text("${p.diagnoses.size} diagnoses · ${p.findings.size} findings · ${p.tests.size} tests · ${p.contexts.size} context modifiers · ${p.stopRules.size} stop rules")
  }
  Text("Development prototype. Not a validated medical device and not for patient-care decisions. Source content is displayed for reference; scoring, adaptive question selection, post-test probability updating and automated triage are not yet validated or fully implemented.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.error)
 }
}
@Composable private fun ProfileSection(title:String,value:String){
 if(value.isNotBlank())Column(verticalArrangement=Arrangement.spacedBy(2.dp)){Text(title,style=MaterialTheme.typography.labelLarge);Text(value,style=MaterialTheme.typography.bodyMedium)}
}
private fun fmt(v:Double)=String.format(Locale.US,"%.2f",v)
