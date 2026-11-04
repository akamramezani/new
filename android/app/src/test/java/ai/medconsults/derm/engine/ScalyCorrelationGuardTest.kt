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
}
