package ai.medconsults.derm.engine

import org.junit.Assert.assertEquals
import org.junit.Test

class ScalyCorrelationGuardTest {
    @Test
    fun unrelatedAndSingleAnsweredFindingsArePreserved() {
        val answers = mapOf(2 to true, 17 to false, 31 to true)
        assertEquals(setOf(2, 17, 31), ScalyCorrelationGuard.retainedIndices(answers))
    }

    @Test
    fun groupSixRetainsEighteenOnlyForNegativeSeventeenAndPositiveEighteen() {
        assertEquals(setOf(18), ScalyCorrelationGuard.retainedIndices(mapOf(17 to false, 18 to true)))
        assertEquals(setOf(17), ScalyCorrelationGuard.retainedIndices(mapOf(17 to false, 18 to false)))
        assertEquals(setOf(17), ScalyCorrelationGuard.retainedIndices(mapOf(17 to true, 18 to true)))
        assertEquals(setOf(17), ScalyCorrelationGuard.retainedIndices(mapOf(17 to true, 18 to false)))
    }

    @Test
    fun psoriasisMorphologyGroupMatchesReferencePriority() {
        assertEquals(setOf(1), ScalyCorrelationGuard.retainedIndices(mapOf(0 to false, 1 to true)))
        assertEquals(setOf(0), ScalyCorrelationGuard.retainedIndices(mapOf(0 to true, 1 to true)))
        assertEquals(setOf(0), ScalyCorrelationGuard.retainedIndices(mapOf(0 to false, 1 to false)))
    }

    @Test
    fun prMorphologyGroupUsesReferencePriorityAndKeepsPartialUnmappedCase() {
        assertEquals(setOf(7), ScalyCorrelationGuard.retainedIndices(mapOf(7 to true, 8 to true, 9 to true)))
        assertEquals(setOf(9), ScalyCorrelationGuard.retainedIndices(mapOf(7 to false, 8 to false, 9 to true)))
        assertEquals(setOf(8), ScalyCorrelationGuard.retainedIndices(mapOf(7 to false, 8 to false, 9 to false)))
        assertEquals(setOf(7), ScalyCorrelationGuard.retainedIndices(mapOf(7 to false, 9 to false)))
    }

    @Test
    fun everyOtherMappedGroupRetainsTheReferenceSelectedFinding() {
        assertEquals(setOf(11), ScalyCorrelationGuard.retainedIndices(mapOf(10 to true, 11 to true)))
        assertEquals(setOf(19), ScalyCorrelationGuard.retainedIndices(mapOf(19 to true, 20 to true)))
        assertEquals(setOf(25), ScalyCorrelationGuard.retainedIndices(mapOf(16 to false, 25 to true)))
        assertEquals(setOf(13), ScalyCorrelationGuard.retainedIndices(mapOf(13 to false, 29 to false)))
    }

    @Test
    fun everyTwoFindingCorrelationGroupKeepsExactlyTheReferenceSelectedMember() {
        val cases = listOf(
            Triple(0, 1, { a: Boolean, b: Boolean -> if (!a && b) 1 else 0 }),
            Triple(10, 11, { _: Boolean, b: Boolean -> if (b) 11 else 10 }),
            Triple(19, 20, { a: Boolean, _: Boolean -> if (a) 19 else 20 }),
            Triple(16, 25, { a: Boolean, b: Boolean -> if (a) 16 else if (b) 25 else 16 }),
            Triple(13, 29, { _: Boolean, b: Boolean -> if (b) 29 else 13 }),
            Triple(17, 18, { a: Boolean, b: Boolean -> if (!a && b) 18 else 17 })
        )
        cases.forEach { (first, second, choose) ->
            listOf(false, true).forEach { firstAnswer ->
                listOf(false, true).forEach { secondAnswer ->
                    val expected = setOf(choose(firstAnswer, secondAnswer))
                    assertEquals(
                        "Group $first/$second for answers $firstAnswer/$secondAnswer",
                        expected,
                        ScalyCorrelationGuard.retainedIndices(mapOf(first to firstAnswer, second to secondAnswer))
                    )
                }
            }
        }
    }

    @Test
    fun everyPrAnswerCombinationKeepsExactlyThePrioritySelectedMember() {
        val values = listOf(false, true)
        values.forEach { a ->
            values.forEach { b ->
                values.forEach { c ->
                    val expected = when {
                        a -> 7
                        c -> 9
                        else -> 8
                    }
                    assertEquals(
                        "PR group for answers 7=$a, 8=$b, 9=$c",
                        setOf(expected),
                        ScalyCorrelationGuard.retainedIndices(mapOf(7 to a, 8 to b, 9 to c))
                    )
                }
            }
        }
    }

    @Test
    fun correlationResolutionNeverRemovesFindingsOutsideItsMappedGroups() {
        val unrelated = setOf(2, 3, 4, 5, 6, 12, 14, 15, 21, 22, 23, 24, 26, 27, 28, 30, 31)
        val answers = unrelated.associateWith { it % 2 == 0 } + mapOf(
            0 to false, 1 to true, 7 to false, 8 to true, 9 to true
        )
        assertEquals(unrelated + setOf(1, 9), ScalyCorrelationGuard.retainedIndices(answers))
    }

}
