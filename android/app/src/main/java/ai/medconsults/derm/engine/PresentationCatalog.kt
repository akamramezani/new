package ai.medconsults.derm.engine

import android.content.res.AssetManager
import org.json.JSONArray
import org.json.JSONObject

data class PresentationDiagnosis(val id:String,val name:String,val baseWeight:Double?,val grade:String,val source:String,val look:String,val supporting:List<String>,val opposing:List<String>,val clinicalFeatures:String,val dermoscopy:String,val histopathology:String,val associations:String,val management:String,val locations:List<String>,val pattern:String)
data class PresentationStopRule(val label:String,val action:String)
data class PresentationFinding(val index:Int,val label:String,val group:String,val likelihoods:Map<String,Pair<Double,Double>>,val grade:String,val source:String)
data class PresentationTest(val index:Int,val label:String,val target:String,val sensitivity:Double?,val specificity:Double?,val grade:String,val source:String,val whenToUse:String,val positive:String,val negative:String,val caveat:String)
data class PresentationContext(val index:Int,val label:String,val ageRange:Pair<Int,Int>?,val sex:String?,val multipliers:Map<String,Double>,val grade:String,val source:String)
data class PresentationData(val id:String,val group:String,val label:String,val question:String,val lead:String,val safetyFlag:String,val stopRules:List<PresentationStopRule>,val findings:List<PresentationFinding>,val diagnoses:List<PresentationDiagnosis>,val tests:List<PresentationTest>,val contexts:List<PresentationContext>)

class PresentationCatalog(private val assets:AssetManager) {
 private val manifest:JSONObject by lazy { assets.open("knowledge/knowledge_manifest.json").bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) } }
 val presentationIds:List<String> get()=manifest.getJSONObject("presentations").keys().asSequence().toList()
 fun load(id:String):PresentationData {
  require(id in presentationIds) { "Unknown presentation: $id" }
  val meta=manifest.getJSONObject("presentations").getJSONObject(id)
  val j=assets.open("knowledge/${meta.getString("file")}").bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
  require(j.optString("id")==id) { "Presentation ID mismatch for $id" }
  val findings=objects(j,"find").mapIndexed { i,o ->
   val factors=linkedMapOf<String,Pair<Double,Double>>(); val f=o.optJSONObject("f")
   if(f!=null) f.keys().forEach { k -> val a=f.optJSONArray(k); if(a!=null&&a.length()>=2) factors[k]=a.optDouble(0) to a.optDouble(1) }
   PresentationFinding(i,o.optString("l"),o.optString("g"),factors,o.optString("c"),o.optString("s"))
  }
  val diagnoses=objects(j,"dx").map { o ->
   PresentationDiagnosis(o.optString("id"),o.optString("n",o.optString("id")),if(o.has("base")&&!o.isNull("base"))o.optDouble("base") else null,o.optString("c"),o.optString("s"),o.optString("look"),strings(o.optJSONArray("fr")),strings(o.optJSONArray("ag")),o.optString("cf"),o.optString("dsc"),o.optString("hp"),o.optString("assoc"),o.optString("mgmt"),strings(o.optJSONArray("z")),o.optString("pat"))
  }
  val tests=objects(j,"test").mapIndexed { i,o -> PresentationTest(i,o.optString("l"),o.optString("tgt"),num(o,"se"),num(o,"sp"),o.optString("c"),o.optString("s"),o.optString("w"),o.optString("p"),o.optString("n"),o.optString("x")) }
  val contexts=objects(j,"ctx").mapIndexed { i,o ->
   val a=o.optJSONArray("age"); val m=linkedMapOf<String,Double>(); val mo=o.optJSONObject("m")
   if(mo!=null) mo.keys().forEach { k -> m[k]=mo.optDouble(k) }
   PresentationContext(i,o.optString("l"),if(a!=null&&a.length()>=2)a.optInt(0) to a.optInt(1) else null,o.optString("sex").takeIf { it.isNotBlank() },m,o.optString("c"),o.optString("s"))
  }
  val stops=objects(j,"stop").map { PresentationStopRule(it.optString("l"),it.optString("a")) }
  return PresentationData(id,j.optString("grp"),j.optString("label",id),j.optString("q"),j.optString("lead"),j.optString("flag"),stops,findings,diagnoses,tests,contexts)
 }
 private fun objects(o:JSONObject,k:String):List<JSONObject>{val a=o.optJSONArray(k)?:JSONArray();return (0 until a.length()).mapNotNull{a.optJSONObject(it)}}
 private fun strings(a:JSONArray?):List<String> = if(a==null) emptyList() else (0 until a.length()).mapNotNull{a.optString(it).takeIf{v->v.isNotBlank()}}
 private fun num(o:JSONObject,k:String):Double?=if(o.has(k)&&!o.isNull(k))o.optDouble(k)else null
}