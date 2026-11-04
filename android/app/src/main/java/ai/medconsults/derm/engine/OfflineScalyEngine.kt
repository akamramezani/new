package ai.medconsults.derm.engine

import android.content.res.AssetManager
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.exp
import kotlin.math.pow

data class Finding(val index: Int, val label: String)
data class FindingContribution(
    val findingIndex: Int,
    val findingLabel: String,
    val answer: Boolean,
    val sourceMultiplier: Double,
    val appliedMultiplier: Double,
    val weightBefore: Double,
    val weightAfter: Double
)
data class RankedDiagnosis(
    val id: String,
    val name: String,
    val probability: Double,
    val base: Double,
    val weight: Double,
    val contributions: List<FindingContribution>
)
data class DroppedFinding(val index: Int, val answer: Boolean, val label: String)
data class ScalyResult(
    val answeredCount: Int,
    val scoredCount: Int,
    val residual: Double,
    val ranked: List<RankedDiagnosis>,
    val dropped: List<DroppedFinding>
)

class OfflineScalyEngine(assets: AssetManager) {
    private val presentation: JSONObject =
        assets.open("knowledge/presentation_scaly.json")
            .bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }

    val presentationLabel: String = presentation.optString("label", "Scaly plaques and patches")
    val lead: String = presentation.optString("lead", "")
    val findings: List<Finding> = jsonArray(presentation, "find").mapIndexed { i, obj ->
        Finding(i, obj.optString("l", "Finding ${i + 1}"))
    }
    val stopRules: List<Pair<String, String>> = jsonArray(presentation, "stop").map { obj ->
        obj.optString("l") to obj.optString("a")
    }
    val safetyFlag: String = presentation.optString("flag", "")

    fun score(answers: Map<Int, Boolean>): ScalyResult {
        require(answers.keys.all { it in findings.indices }) { "Unknown finding index." }

        val retained = answers.keys.toMutableSet()
        fun resolve(indices: List<Int>, selector: () -> Int) {
            val available = indices.filter { it in answers }
            if (available.size < 2) return
            val selected = selector()
            if (selected !in available) return
            available.filter { it != selected }.forEach(retained::remove)
        }

        resolve(listOf(0, 1)) {
            if (answers[0] == false && answers[1] == true) 1 else 0
        }
        resolve(listOf(10, 11)) {
            if (answers[11] == true) 11 else 10
        }
        resolve(listOf(19, 20)) {
            if (answers[19] == true) 19 else 20
        }
        resolve(listOf(16, 25)) {
            if (answers[16] == true) 16 else if (answers[25] == true) 25 else 16
        }
        resolve(listOf(13, 29)) {
            if (answers[29] == true) 29 else 13
        }
        resolve(listOf(17, 18)) {
            if (answers[17] == false) 18 else 17
        }

        val prGroup = listOf(7, 8, 9).filter { it in answers }
        if (prGroup.size >= 2) {
            val selected = when {
                answers[7] == true -> 7
                answers[9] == true -> 9
                8 in answers -> 8
                7 in answers -> 7
                9 in answers -> 9
                else -> null
            }
            if (selected != null) prGroup.filter { it != selected }.forEach(retained::remove)
        }

        val dropped = answers.keys.filter { it !in retained }.sorted().map {
            DroppedFinding(it, answers.getValue(it), findings[it].label)
        }
        val effective = retained.intersect(answers.keys)
        val residual = 0.05 + 0.06 * exp(-effective.size / 3.0)
        val diagnoses = jsonArray(presentation, "dx")
        val weights = linkedMapOf<String, Double>()
        val names = linkedMapOf<String, String>()
        val bases = linkedMapOf<String, Double>()
        val contributions = linkedMapOf<String, MutableList<FindingContribution>>()

        diagnoses.forEach { dx ->
            val id = dx.getString("id")
            val base = dx.getDouble("base")
            require(base.isFinite() && base > 0.0) { "Invalid base weight for $id" }
            weights[id] = base
            names[id] = dx.optString("n", id)
            bases[id] = base
            contributions[id] = mutableListOf()
        }

        effective.sorted().forEach { index ->
            val finding = jsonArray(presentation, "find")[index]
            val modifiers = finding.optJSONObject("f") ?: JSONObject()
            val multiplierPosition = if (answers.getValue(index)) 0 else 1
            modifiers.keys().forEach { diagnosisId ->
                if (diagnosisId in weights) {
                    val pair = modifiers.getJSONArray(diagnosisId)
                    require(pair.length() == 2) { "Invalid modifier for $diagnosisId at finding $index" }
                    val multiplier = pair.getDouble(multiplierPosition)
                    require(multiplier.isFinite() && multiplier > 0.0) {
                        "Invalid multiplier for $diagnosisId at finding $index"
                    }
                    val before = weights.getValue(diagnosisId)
                    val applied = multiplier.pow(0.7)
                    val after = before * applied
                    weights[diagnosisId] = after
                    contributions.getValue(diagnosisId).add(
                        FindingContribution(
                            findingIndex = index,
                            findingLabel = findings[index].label,
                            answer = answers.getValue(index),
                            sourceMultiplier = multiplier,
                            appliedMultiplier = applied,
                            weightBefore = before,
                            weightAfter = after
                        )
                    )
                }
            }
        }

        val total = weights.values.sum()
        require(total.isFinite() && total > 0.0) { "Invalid total diagnosis weight." }
        val ranked = weights.map { (id, weight) ->
            RankedDiagnosis(
                id = id,
                name = names.getValue(id),
                probability = (1.0 - residual) * weight / total,
                base = bases.getValue(id),
                weight = weight,
                contributions = contributions.getValue(id).toList()
            )
        }.sortedByDescending { it.probability }

        return ScalyResult(
            answeredCount = answers.size,
            scoredCount = effective.size,
            residual = residual,
            ranked = ranked,
            dropped = dropped
        )
    }

    private fun jsonArray(root: JSONObject, key: String): List<JSONObject> {
        val array: JSONArray = root.getJSONArray(key)
        return (0 until array.length()).map { array.getJSONObject(it) }
    }
}
