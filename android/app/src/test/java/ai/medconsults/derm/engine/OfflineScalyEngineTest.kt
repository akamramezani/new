package ai.medconsults.derm.engine

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.pow

class OfflineScalyEngineTest {
    private fun finding(label: String, factors: JSONObject = JSONObject()) =
        JSONObject().put("l", label).put("f", factors)

    private fun fixture(): JSONObject {
        val diagnoses = JSONArray()
            .put(JSONObject().put("id", "A").put("n", "Diagnosis A").put("base", 2.0))
            .put(JSONObject().put("id", "B").put("n", "Diagnosis B").put("base", 1.0))
        val findings = JSONArray()
            .put(finding("unused 0"))
            .put(finding("unused 1"))
            .put(finding("positive evidence", JSONObject()
                .put("A", JSONArray().put(4.0).put(0.25))
                .put("B", JSONArray().put(0.5).put(2.0))))
            .put(finding("negative evidence", JSONObject()
                .put("A", JSONArray().put(0.5).put(1.0))
                .put("B", JSONArray().put(1.0).put(0.5))))
        return JSONObject()
            .put("label", "Fixture")
            .put("lead", "")
            .put("find", findings)
            .put("dx", diagnoses)
            .put("stop", JSONArray())
            .put("flag", "")
    }

    private fun engine() = OfflineScalyEngine(fixture(), true)

    @Test
    fun emptyAnswersReturnBaselineSharesAndExpectedResidualMass() {
        val result = engine().score(emptyMap())
        val expectedResidual = 0.05 + 0.06 * exp(0.0)
        assertEquals(0, result.answeredCount)
        assertEquals(0, result.scoredCount)
        assertEquals(expectedResidual, result.residual, 1e-12)
        assertEquals(2, result.ranked.size)
        assertEquals((1.0 - expectedResidual) * 2.0 / 3.0,
            result.ranked.first { it.id == "A" }.probability, 1e-12)
        assertEquals((1.0 - expectedResidual) / 3.0,
            result.ranked.first { it.id == "B" }.probability, 1e-12)
        assertEquals(1.0 - expectedResidual, result.ranked.sumOf { it.probability }, 1e-12)
    }

    @Test
    fun multipliersAndContributionTraceReconstructFinalWeights() {
        val result = engine().score(mapOf(2 to true, 3 to false))
        val a = result.ranked.first { it.id == "A" }
        val b = result.ranked.first { it.id == "B" }
        val expectedA = 2.0 * 4.0.pow(0.7) * 1.0.pow(0.7)
        val expectedB = 1.0 * 0.5.pow(0.7) * 0.5.pow(0.7)
        assertEquals(expectedA, a.weight, 1e-12)
        assertEquals(expectedB, b.weight, 1e-12)
        assertEquals(2, a.contributions.size)
        assertEquals(2, b.contributions.size)
        listOf(a, b).forEach { diagnosis ->
            assertEquals(diagnosis.weight, diagnosis.contributions.last().weightAfter, 1e-12)
            diagnosis.contributions.forEach { contribution ->
                assertEquals(contribution.weightBefore * contribution.appliedMultiplier,
                    contribution.weightAfter, 1e-12)
            }
        }
        assertTrue("Diagnosis A should rank above B", a.probability > b.probability)
        assertEquals(1.0 - result.residual, result.ranked.sumOf { it.probability }, 1e-12)
        assertEquals(1.0 - result.residual, result.ranked.sumOf { it.baseProbability }, 1e-12)
    }

    @Test
    fun unknownFindingIndicesAreRejected() {
        var rejected = false
        try {
            engine().score(mapOf(99 to true))
        } catch (_: IllegalArgumentException) {
            rejected = true
        }
        assertTrue("Unknown finding index should be rejected", rejected)
    }
}
