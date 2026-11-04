package ai.medconsults.derm.engine

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PythonGoldenVectorTest {
    private fun resource(name: String): String =
        javaClass.classLoader!!.getResourceAsStream(name)!!
            .bufferedReader(Charsets.UTF_8).use { it.readText() }

    @Test
    fun androidScorerMatchesPythonReferenceGoldenVectors() {
        val presentation = JSONObject(resource("presentation_scaly.json"))
        val vectors = JSONObject(resource("scoring_golden_vectors.json"))
        assertEquals("scoring.py::score_findings", vectors.getString("generator"))
        val cases = vectors.getJSONArray("cases")
        assertEquals(vectors.getInt("case_count"), cases.length())

        val engine = OfflineScalyEngine(presentation, true)
        val failures = mutableListOf<String>()

        for (caseIndex in 0 until cases.length()) {
            val case = cases.getJSONObject(caseIndex)
            val answersJson = case.getJSONObject("answers")
            val answers = mutableMapOf<Int, Boolean>()
            val answerKeys = answersJson.keys()
            while (answerKeys.hasNext()) {
                val key = answerKeys.next()
                answers[key.toInt()] = answersJson.getString(key) == "y"
            }

            val expected = case.getJSONObject("expected")
            val actual = engine.score(answers)
            val name = case.getString("name")

            fun check(condition: Boolean, detail: String) {
                if (!condition) failures += "$name: $detail"
            }

            check(actual.answeredCount == expected.getInt("answered"),
                "answered count expected ${expected.getInt("answered")}, got ${actual.answeredCount}")
            check(actual.scoredCount == expected.getInt("scored"),
                "scored count expected ${expected.getInt("scored")}, got ${actual.scoredCount}")
            check(kotlin.math.abs(actual.residual - expected.getDouble("residual")) <= 1e-10,
                "residual mismatch: expected ${expected.getDouble("residual")}, got ${actual.residual}")

            val expectedDropped = expected.getJSONArray("dropped")
            val expectedDroppedIndices = (0 until expectedDropped.length()).map { expectedDropped.getInt(it) }
            check(actual.dropped.map { it.index }.sorted() == expectedDroppedIndices,
                "dropped indices mismatch")

            val expectedRanked = expected.getJSONArray("ranked")
            val expectedIds = (0 until expectedRanked.length()).map {
                expectedRanked.getJSONObject(it).getString("id")
            }
            check(actual.ranked.map { it.id } == expectedIds, "ranking order mismatch")

            for (rankIndex in 0 until expectedRanked.length()) {
                val row = expectedRanked.getJSONObject(rankIndex)
                val actualRow = actual.ranked.getOrNull(rankIndex)
                if (actualRow == null) {
                    check(false, "missing ranked row $rankIndex")
                    continue
                }
                check(actualRow.id == row.getString("id"), "diagnosis ID mismatch at rank $rankIndex")
                check(kotlin.math.abs(actualRow.weight - row.getDouble("weight")) <=
                    1e-9 * maxOf(1.0, kotlin.math.abs(row.getDouble("weight"))),
                    "weight mismatch for ${actualRow.id}")
                check(kotlin.math.abs(actualRow.probability - row.getDouble("probability")) <= 1e-10,
                    "probability mismatch for ${actualRow.id}")
            }
        }

        if (failures.isNotEmpty()) failures.forEach { println("GOLDEN_VECTOR_MISMATCH: $it") }
        assertTrue(
            "Python golden-vector discrepancies (${failures.size}):\n" + failures.take(30).joinToString("\n"),
            failures.isEmpty()
        )
    }
}
