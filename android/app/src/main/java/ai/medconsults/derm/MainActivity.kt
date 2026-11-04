package ai.medconsults.derm

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import ai.medconsults.derm.engine.OfflineScalyEngine
import ai.medconsults.derm.engine.ScalyResult
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val engine = OfflineScalyEngine(assets)
        setContent { MaterialTheme { ScalyAssessmentScreen(engine) } }
    }
}

@Composable
private fun ScalyAssessmentScreen(engine: OfflineScalyEngine) {
    val answers = remember { mutableStateMapOf<Int, Boolean>() }
    var result by remember { mutableStateOf<ScalyResult?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("MedConsults", style = MaterialTheme.typography.headlineMedium)
        Text("Dermatology Differential Engine", style = MaterialTheme.typography.titleLarge)
        Text("Shortlist · Discriminate · Confirm", style = MaterialTheme.typography.bodyLarge)
        HorizontalDivider()

        Text(engine.presentationLabel, style = MaterialTheme.typography.titleLarge)
        Text(engine.lead, style = MaterialTheme.typography.bodyMedium)

        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Safety review", style = MaterialTheme.typography.titleMedium)
                Text(engine.safetyFlag)
                engine.stopRules.forEachIndexed { index, rule ->
                    Text("${index + 1}. ${rule.first}", style = MaterialTheme.typography.bodyMedium)
                    Text(rule.second, style = MaterialTheme.typography.bodySmall)
                }
            }
        }

        Text("Clinical findings", style = MaterialTheme.typography.titleLarge)
        Text("Choose Yes or No for findings you have assessed. Leave unassessed findings unanswered.")

        engine.findings.forEach { finding ->
            Card {
                Column(Modifier.fillMaxWidth().padding(12.dp)) {
                    Text("${finding.index + 1}. ${finding.label}", style = MaterialTheme.typography.bodyLarge)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(
                            selected = answers[finding.index] == true,
                            onClick = { answers[finding.index] = true; result = null },
                            label = { Text("Yes") }
                        )
                        FilterChip(
                            selected = answers[finding.index] == false,
                            onClick = { answers[finding.index] = false; result = null },
                            label = { Text("No") }
                        )
                        if (finding.index in answers) {
                            TextButton(onClick = { answers.remove(finding.index); result = null }) {
                                Text("Clear")
                            }
                        }
                    }
                }
            }
        }

        Button(
            onClick = {
                try {
                    result = engine.score(answers.toMap())
                    error = null
                } catch (e: Exception) {
                    result = null
                    error = e.message ?: "Scoring failed"
                }
            },
            enabled = answers.isNotEmpty(),
            modifier = Modifier.fillMaxWidth()
        ) { Text("Calculate differential") }

        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }

        result?.let { output ->
            HorizontalDivider()
            Text("Differential ranking", style = MaterialTheme.typography.headlineSmall)
            Text("Answered: ${output.answeredCount} · Scored after correlation handling: ${output.scoredCount}")
            Text("Residual: ${String.format(Locale.US, "%.4f", output.residual)}")
            output.ranked.forEachIndexed { index, dx ->
                ListItem(
                    headlineContent = { Text("${index + 1}. ${dx.name}") },
                    supportingContent = { Text("Model weight: ${String.format(Locale.US, "%.4f", dx.weight)}") },
                    trailingContent = {
                        Text(String.format(Locale.US, "%.1f%%", dx.probability * 100.0))
                    }
                )
            }
            if (output.dropped.isNotEmpty()) {
                Text("Correlated findings excluded from scoring", style = MaterialTheme.typography.titleMedium)
                output.dropped.forEach { Text("• ${it.index + 1}. ${it.label}") }
            }
            Text(
                "Prototype only. The scaly finding-ranking algorithm is implemented from the repository's reconstructed scoring reference. Context modifiers, adaptive question selection, test updating, and full red-flag gating are not yet integrated. Do not use for patient-care decisions.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error
            )
        }
    }
}
