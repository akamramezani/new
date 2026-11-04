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
import ai.medconsults.derm.engine.PresentationCatalog
import ai.medconsults.derm.engine.PresentationData
import ai.medconsults.derm.engine.ScalyResult
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val catalog = PresentationCatalog(assets)
        val scalyEngine = OfflineScalyEngine(assets)
        setContent { MaterialTheme { DermatologyHome(catalog, scalyEngine) } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DermatologyHome(catalog: PresentationCatalog, scalyEngine: OfflineScalyEngine) {
    val ids = remember { catalog.presentationIds }
    var selectedId by remember { mutableStateOf("scaly") }
    var menuExpanded by remember { mutableStateOf(false) }
    var data by remember { mutableStateOf<PresentationData?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    val answers = remember(selectedId) { mutableStateMapOf<Int, Boolean>() }
    var result by remember(selectedId) { mutableStateOf<ScalyResult?>(null) }
    var scoreError by remember(selectedId) { mutableStateOf<String?>(null) }

    LaunchedEffect(selectedId) {
        try {
            data = catalog.load(selectedId)
            loadError = null
        } catch (e: Exception) {
            data = null
            loadError = e.message ?: "Could not load presentation"
        }
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("MedConsults", style = MaterialTheme.typography.headlineMedium)
        Text("Dermatology Differential Engine", style = MaterialTheme.typography.titleLarge)
        Text("Shortlist · Discriminate · Confirm", style = MaterialTheme.typography.bodyLarge)
        Text("Offline knowledge package · ${ids.size} presentations", style = MaterialTheme.typography.labelMedium)
        HorizontalDivider()

        ExposedDropdownMenuBox(
            expanded = menuExpanded,
            onExpandedChange = { menuExpanded = !menuExpanded }
        ) {
            OutlinedTextField(
                value = data?.label ?: selectedId,
                onValueChange = {},
                readOnly = true,
                label = { Text("Clinical presentation") },
                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = menuExpanded) },
                modifier = Modifier.menuAnchor().fillMaxWidth()
            )
            ExposedDropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                ids.forEach { id ->
                    val label = runCatching { catalog.load(id).label }.getOrDefault(id)
                    DropdownMenuItem(text = { Text(label) }, onClick = {
                        selectedId = id
                        menuExpanded = false
                    })
                }
            }
        }

        loadError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        data?.let { presentation ->
            Text(presentation.group, style = MaterialTheme.typography.labelLarge)
            Text(presentation.label, style = MaterialTheme.typography.titleLarge)
            if (presentation.question.isNotBlank()) Text(presentation.question, style = MaterialTheme.typography.titleMedium)
            Text(presentation.lead, style = MaterialTheme.typography.bodyMedium)

            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Safety review — read before differential assessment", style = MaterialTheme.typography.titleMedium)
                    if (presentation.safetyFlag.isNotBlank()) Text(presentation.safetyFlag)
                    presentation.stopRules.forEachIndexed { index, rule ->
                        Text("${index + 1}. ${rule.label}", style = MaterialTheme.typography.bodyMedium)
                        if (rule.action.isNotBlank()) Text(rule.action, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            Text("Clinical findings", style = MaterialTheme.typography.titleLarge)
            Text("Choose Yes or No only for findings you have assessed. Leave unassessed findings unanswered.")
            presentation.findings.forEach { finding ->
                Card {
                    Column(Modifier.fillMaxWidth().padding(12.dp)) {
                        Text("${finding.index + 1}. ${finding.label}", style = MaterialTheme.typography.bodyLarge)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            FilterChip(selected = answers[finding.index] == true,
                                onClick = { answers[finding.index] = true; result = null }, label = { Text("Yes") })
                            FilterChip(selected = answers[finding.index] == false,
                                onClick = { answers[finding.index] = false; result = null }, label = { Text("No") })
                            if (finding.index in answers) {
                                TextButton(onClick = { answers.remove(finding.index); result = null }) { Text("Clear") }
                            }
                        }
                    }
                }
            }

            if (selectedId == "scaly") {
                Button(
                    onClick = {
                        try {
                            result = scalyEngine.score(answers.toMap())
                            scoreError = null
                        } catch (e: Exception) {
                            result = null
                            scoreError = e.message ?: "Scoring failed"
                        }
                    },
                    enabled = answers.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth()
                ) { Text("Calculate scaly differential") }
                scoreError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                result?.let { output ->
                    HorizontalDivider()
                    Text("Differential ranking", style = MaterialTheme.typography.headlineSmall)
                    Text("Answered: ${output.answeredCount} · Scored after correlation handling: ${output.scoredCount}")
                    Text("Residual: ${String.format(Locale.US, "%.4f", output.residual)}")
                    output.ranked.forEachIndexed { index, dx ->
                        ListItem(
                            headlineContent = { Text("${index + 1}. ${dx.name}") },
                            supportingContent = { Text("Model weight: ${String.format(Locale.US, "%.4f", dx.weight)}") },
                            trailingContent = { Text(String.format(Locale.US, "%.1f%%", dx.probability * 100.0)) }
                        )
                    }
                    if (output.dropped.isNotEmpty()) {
                        Text("Correlated findings excluded from scoring", style = MaterialTheme.typography.titleMedium)
                        output.dropped.forEach { Text("• ${it.index + 1}. ${it.label}") }
                    }
                }
            } else {
                HorizontalDivider()
                Text("Diagnosis reference list — not ranked", style = MaterialTheme.typography.titleLarge)
                Text(
                    "The offline knowledge package is available for this presentation, but its scoring, context modifiers, and triage logic have not yet been implemented and validated. No probability ranking is shown.",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium
                )
                presentation.diagnoses.forEach { dx ->
                    ListItem(headlineContent = { Text(dx.name) }, supportingContent = { Text("Reference ID: ${dx.id}") })
                }
            }

            HorizontalDivider()
            Text("Knowledge package", style = MaterialTheme.typography.titleMedium)
            Text("${presentation.diagnoses.size} diagnoses · ${presentation.findings.size} findings · ${presentation.testCount} tests · ${presentation.contextModifierCount} context modifiers · ${presentation.stopRules.size} urgent rules")
        }

        Text(
            "Development prototype only. Not a validated medical device and not for patient-care decisions. Safety reminders are informational; the app does not yet enforce automated red-flag triage. Only the scaly ranking component is currently implemented, and it still requires parity testing against the production engine.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error
        )
    }
}
