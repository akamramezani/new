package ai.medconsults.derm.engine

import android.content.res.AssetManager
import org.json.JSONArray
import org.json.JSONObject

data class PresentationDiagnosis(val id: String, val name: String, val baseWeight: Double?)
data class PresentationStopRule(val label: String, val action: String)
data class PresentationFinding(val index: Int, val label: String)

data class PresentationData(
    val id: String,
    val group: String,
    val label: String,
    val question: String,
    val lead: String,
    val safetyFlag: String,
    val stopRules: List<PresentationStopRule>,
    val findings: List<PresentationFinding>,
    val diagnoses: List<PresentationDiagnosis>,
    val testCount: Int,
    val contextModifierCount: Int
)

class PresentationCatalog(private val assets: AssetManager) {
    private val manifest: JSONObject by lazy {
        assets.open("knowledge/knowledge_manifest.json")
            .bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
    }

    val presentationIds: List<String>
        get() = manifest.getJSONObject("presentations").keys().asSequence().toList()

    fun load(id: String): PresentationData {
        require(id in presentationIds) { "Unknown presentation: $id" }
        val metadata = manifest.getJSONObject("presentations").getJSONObject(id)
        val json = assets.open("knowledge/${metadata.getString("file")}")
            .bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }
        require(json.optString("id") == id) { "Presentation ID mismatch for $id" }

        val findings = jsonObjects(json, "find").mapIndexed { index, item ->
            PresentationFinding(index, item.optString("l", "Finding ${index + 1}"))
        }
        val diagnoses = jsonObjects(json, "dx").map { item ->
            PresentationDiagnosis(
                id = item.optString("id"),
                name = item.optString("n", item.optString("id")),
                baseWeight = if (item.has("base") && !item.isNull("base")) item.optDouble("base") else null
            )
        }
        val stops = jsonObjects(json, "stop").map { item ->
            PresentationStopRule(item.optString("l"), item.optString("a"))
        }

        return PresentationData(
            id = id,
            group = json.optString("grp"),
            label = json.optString("label", id),
            question = json.optString("q"),
            lead = json.optString("lead"),
            safetyFlag = json.optString("flag"),
            stopRules = stops,
            findings = findings,
            diagnoses = diagnoses,
            testCount = metadata.optInt("tests"),
            contextModifierCount = metadata.optInt("context_modifiers")
        )
    }

    private fun jsonObjects(root: JSONObject, key: String): List<JSONObject> {
        val array: JSONArray = root.optJSONArray(key) ?: JSONArray()
        return (0 until array.length()).mapNotNull { index ->
            array.optJSONObject(index)
        }
    }
}
