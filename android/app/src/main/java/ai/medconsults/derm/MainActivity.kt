package ai.medconsults.derm

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ai.medconsults.derm.engine.*
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val catalog = PresentationCatalog(assets)
        val engine = OfflineScalyEngine(assets)
        setContent { MaterialTheme { DermatologyApp(catalog, engine) } }
    }
}

private enum class Screen(val title: String, val glyph: String) {
    HOME("Overview", "⌂"), FINDINGS("Findings", "＋"), DIFFERENTIAL("Differential", "▤"),
    TESTS("Tests", "⚕"), REFERENCE("Reference", "☰")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DermatologyApp(catalog: PresentationCatalog, engine: OfflineScalyEngine) {
    val ids = remember { catalog.presentationIds }
    var selectedId by remember { mutableStateOf("scaly") }
    var menu by remember { mutableStateOf(false) }
    var screen by remember { mutableStateOf(Screen.HOME) }
    var data by remember { mutableStateOf<PresentationData?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val answers = remember(selectedId) { mutableStateMapOf<Int, Boolean>() }
    var result by remember(selectedId) { mutableStateOf<ScalyResult?>(null) }
    var scoreError by remember(selectedId) { mutableStateOf<String?>(null) }
    var selectedDx by remember(selectedId) { mutableStateOf<String?>(null) }
    var selectedTest by remember(selectedId) { mutableStateOf<Int?>(null) }
    var search by remember(selectedId) { mutableStateOf("") }
    LaunchedEffect(selectedId) {
        try { data = catalog.load(selectedId); error = null }
        catch (e: Exception) { data = null; error = e.message ?: "Unable to load presentation" }
    }
    Scaffold(
        topBar = {
            TopAppBar(title = {
                Column {
                    Text("MedConsults", fontWeight = FontWeight.Bold)
                    Text("DERMATOLOGY DECISION SUPPORT", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                }
            }, actions = { AssistChip(onClick = {}, label = { Text("OFFLINE") }); Spacer(Modifier.width(8.dp)) })
        },
        bottomBar = {
            NavigationBar {
                Screen.values().forEach { item ->
                    NavigationBarItem(selected = screen == item, onClick = { screen = item },
                        icon = { Text(item.glyph) }, label = { Text(item.title, maxLines = 1) })
                }
            }
        }
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            ExposedDropdownMenuBox(expanded = menu, onExpandedChange = { menu = !menu }) {
                OutlinedTextField(value = data?.label ?: selectedId, onValueChange = {}, readOnly = true,
                    label = { Text("Presenting morphology") }, trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(menu) },
                    modifier = Modifier.menuAnchor().fillMaxWidth(), shape = RoundedCornerShape(14.dp))
                ExposedDropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    ids.forEach { id -> DropdownMenuItem(
                        text = { Text(runCatching { catalog.load(id).label }.getOrDefault(id)) },
                        onClick = { selectedId = id; menu = false; screen = Screen.HOME })
                    }
                }
            }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            data?.let { p ->
                when (screen) {
                    Screen.HOME -> HomeScreen(p, answers.size, result, scoreError,
                        onFindings = { screen = Screen.FINDINGS },
                        onCalculate = {
                            try { result = engine.score(answers.toMap(), selectedId); scoreError = null; screen = Screen.DIFFERENTIAL }
                            catch (e: Exception) { scoreError = e.message ?: "Scoring failed" }
                        })
                    Screen.FINDINGS -> FindingsScreen(p, answers, search, { search = it }) { result = null; scoreError = null }
                    Screen.DIFFERENTIAL -> DifferentialScreen(p, result, selectedDx, { selectedDx = it },
                        answers.size, scoreError, {
                            try { result = engine.score(answers.toMap()); scoreError = null }
                            catch (e: Exception) { scoreError = e.message ?: "Scoring failed" }
                        })
                    Screen.TESTS -> TestsScreen(p, selectedTest) { selectedTest = it }
                    Screen.REFERENCE -> ReferenceScreen(p, selectedDx) { selectedDx = it }
                }
            }
        }
    }
}

@Composable
private fun HomeScreen(p: PresentationData, answered: Int, result: ScalyResult?, error: String?,
                       onFindings: () -> Unit, onCalculate: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(p.group.uppercase(Locale.US), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
        Text(p.label, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(p.question, style = MaterialTheme.typography.titleMedium)
        if (p.lead.isNotBlank()) Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
            Text(p.lead, Modifier.padding(14.dp))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Metric("DIAGNOSES", p.diagnoses.size.toString(), Modifier.weight(1f))
            Metric("FINDINGS", p.findings.size.toString(), Modifier.weight(1f))
            Metric("TESTS", p.tests.size.toString(), Modifier.weight(1f))
        }
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Safety and escalation", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(p.safetyFlag)
                p.stopRules.take(3).forEach { rule ->
                    Text("• " + rule.label, fontWeight = FontWeight.SemiBold)
                    Text(rule.action, style = MaterialTheme.typography.bodySmall)
                }
                if (p.stopRules.size > 3) Text(p.stopRules.size.toString() + " escalation rules available in Reference.")
                Text("Reference warnings only; automated triage is not implemented.", style = MaterialTheme.typography.labelSmall)
            }
        }
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Assessment progress", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text(answered.toString() + " of " + p.findings.size + " findings answered", style = MaterialTheme.typography.headlineSmall)
                LinearProgressIndicator(progress = { if (p.findings.isEmpty()) 0f else answered.toFloat() / p.findings.size },
                    modifier = Modifier.fillMaxWidth().height(8.dp))
                Button(onClick = onFindings, modifier = Modifier.fillMaxWidth()) { Text("Open clinical findings") }
                OutlinedButton(onClick = onCalculate, enabled = answered > 0, modifier = Modifier.fillMaxWidth()) {
                    Text("Calculate provisional differential")
                }
                if (p.id != "scaly") Text("Generic reconstructed scoring only: default residual 0.11; no presentation-specific correlation or residual validation.", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        }
        if (result != null) {
            Text("Latest provisional leaders", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            result.ranked.take(3).forEachIndexed { i, dx -> ProbabilityBar((i + 1).toString() + ". " + dx.name, dx.probability) }
        }
        Text("How the workflow works", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Workflow("01", "Characterise", "Record positive and negative morphological findings.")
        Workflow("02", "Discriminate", "Review the ranked differential and evidence for each diagnosis.")
        Workflow("03", "Confirm", "Choose investigations that distinguish the leading diagnoses.")
        Text("Development prototype · Not validated for clinical decisions", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall)
        Spacer(Modifier.height(10.dp))
    }
}

@Composable
private fun FindingsScreen(p: PresentationData, answers: MutableMap<Int, Boolean>, search: String,
                           onSearch: (String) -> Unit, onChange: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Text("Clinical findings", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(answers.size.toString() + " answered · " + (p.findings.size - answers.size) + " unanswered")
        OutlinedTextField(value = search, onValueChange = onSearch, label = { Text("Search findings") },
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), contentPadding = PaddingValues(bottom = 16.dp)) {
            items(p.findings.filter { search.isBlank() || it.label.contains(search, true) }, key = { it.index }) { f ->
                Card {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text((f.index + 1).toString() + ". " + f.label, fontWeight = FontWeight.Medium)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            FilterChip(selected = answers[f.index] == true, onClick = { answers[f.index] = true; onChange() }, label = { Text("Present") })
                            FilterChip(selected = answers[f.index] == false, onClick = { answers[f.index] = false; onChange() }, label = { Text("Absent") })
                            if (f.index in answers) TextButton(onClick = { answers.remove(f.index); onChange() }) { Text("Clear") }
                        }
                        Row {
                            Text("Group: " + f.group, style = MaterialTheme.typography.labelSmall)
                            Spacer(Modifier.weight(1f))
                            Text("Grade " + f.grade, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                        }
                        if (f.likelihoods.isNotEmpty()) {
                            var expanded by remember(f.index) { mutableStateOf(false) }
                            TextButton(onClick = { expanded = !expanded }, contentPadding = PaddingValues(0.dp)) {
                                Text(if (expanded) "Hide likelihood ratios" else "Show likelihood ratios")
                            }
                            if (expanded) {
                                Text(f.likelihoods.entries.joinToString(" · ") { it.key + ": " + fmt(it.value.first) + " / " + fmt(it.value.second) },
                                    style = MaterialTheme.typography.bodySmall)
                                Text(f.source, style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DifferentialScreen(p: PresentationData, result: ScalyResult?, selected: String?, onSelect: (String?) -> Unit,
                               answered: Int, error: String?, onCalculate: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Text("Differential diagnosis", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("Ranked shortlist and visual comparison", color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (result == null) {
            EmptyCard("No result calculated", "Complete the findings assessment and calculate the provisional ranking.")
            Button(onClick = onCalculate, enabled = answered > 0, modifier = Modifier.fillMaxWidth()) { Text("Calculate ranking") }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Metric("ANSWERED", result.answeredCount.toString(), Modifier.weight(1f))
                Metric("COUNTED", result.scoredCount.toString(), Modifier.weight(1f))
                Metric("RESIDUAL", fmt(result.residual * 100) + "%", Modifier.weight(1f))
            }
            Text("Relative ranking chart", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            if (p.id != "scaly") Text("Generic reference scoring · fixed 0.11 residual · no presentation-specific correlation handling. Not clinically validated.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            Text("Bars show the reconstructed model's normalised weights, not validated clinical probabilities.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            LazyColumn(verticalArrangement = Arrangement.spacedBy(7.dp), contentPadding = PaddingValues(bottom = 16.dp)) {
                items(result.ranked, key = { it.id }) { dx ->
                    Card(Modifier.fillMaxWidth().clickable { onSelect(if (selected == dx.id) null else dx.id) }) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(dx.name, Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                                Text(fmt(dx.probability * 100) + "%", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                            }
                            Text("After entered findings", style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            ProbabilityBar("", dx.probability)
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("Baseline share", Modifier.weight(1f), style = MaterialTheme.typography.labelSmall)
                                Text(fmt(dx.baseProbability * 100) + "%", style = MaterialTheme.typography.labelSmall)
                            }
                            ProbabilityBar("", dx.baseProbability)
                            Text("Change from baseline: " +
                                (if (dx.probability - dx.baseProbability >= 0) "+" else "") +
                                fmt((dx.probability - dx.baseProbability) * 100) + " percentage points" +
                                " · Model weight " + fmt(dx.weight) + " (base " + fmt(dx.base) + ")",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                            if (selected == dx.id) {
                                Text("Why this diagnosis has this model weight", fontWeight = FontWeight.Bold)
                                Text("Starting weight: " + fmt(dx.base), style = MaterialTheme.typography.bodySmall)
                                if (dx.contributions.isEmpty()) {
                                    Text("No retained answered finding has a factor for this diagnosis; its weight remains at baseline.",
                                        style = MaterialTheme.typography.bodySmall)
                                } else {
                                    dx.contributions.forEach { contribution ->
                                        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                                            Column(Modifier.padding(9.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                                Text((if (contribution.answer) "Present · " else "Absent · ") + contribution.findingLabel,
                                                    fontWeight = FontWeight.Medium)
                                                Text("Source factor ×" + fmt(contribution.sourceMultiplier) +
                                                    " → applied ×" + fmt(contribution.appliedMultiplier),
                                                    style = MaterialTheme.typography.bodySmall)
                                                Text("Weight " + fmt(contribution.weightBefore) + " → " +
                                                    fmt(contribution.weightAfter),
                                                    style = MaterialTheme.typography.labelSmall)
                                            }
                                        }
                                    }
                                }
                                Text("Final model weight: " + fmt(dx.weight) +
                                    " · Normalised displayed share: " + fmt(dx.probability * 100) + "%",
                                    fontWeight = FontWeight.SemiBold)
                                val d = p.diagnoses.firstOrNull { it.id == dx.id }
                                if (d != null) DiagnosisDetails(d)
                            }
                        }
                    }
                }
                if (result.dropped.isNotEmpty()) item {
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                        Column(Modifier.padding(12.dp)) {
                            Text("Correlated findings not double-counted", fontWeight = FontWeight.Bold)
                            result.dropped.forEach { Text("• " + it.label + " (" + if (it.answer) "present)" else "absent)") }
                        }
                    }
                }
                item { OutlinedButton(onClick = onCalculate, modifier = Modifier.fillMaxWidth()) { Text("Recalculate") } }
                item { Text("This reconstructed scorer has not been shown equivalent to the live website or clinically validated.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall) }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TestsScreen(p: PresentationData, selected: Int?, onSelect: (Int?) -> Unit) {
    var targetMenu by remember(p.id) { mutableStateOf(false) }
    val allTargets = "All targets"
    val targets = remember(p.id) {
        listOf(allTargets) + p.tests.map { it.target }.filter { it.isNotBlank() }.distinct().sorted()
    }
    var selectedTarget by remember(p.id) { mutableStateOf(allTargets) }
    val visibleTests = p.tests.filter { selectedTarget == allTargets || it.target == selectedTarget }
    Column(Modifier.fillMaxSize()) {
        Text("Investigations and confirmation", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(visibleTests.size.toString() + " of " + p.tests.size + " source tests · tap a test for interpretation")
        ExposedDropdownMenuBox(expanded = targetMenu, onExpandedChange = { targetMenu = !targetMenu }) {
            OutlinedTextField(
                value = selectedTarget,
                onValueChange = {},
                readOnly = true,
                label = { Text("Filter by exact source target") },
                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(targetMenu) },
                modifier = Modifier.menuAnchor().fillMaxWidth(),
                shape = RoundedCornerShape(14.dp)
            )
            ExposedDropdownMenu(expanded = targetMenu, onDismissRequest = { targetMenu = false }) {
                targets.forEach { target ->
                    DropdownMenuItem(
                        text = { Text(target) },
                        onClick = { selectedTarget = target; targetMenu = false }
                    )
                }
            }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), contentPadding = PaddingValues(bottom = 16.dp)) {
            items(visibleTests, key = { it.index }) { t ->
                Card(Modifier.fillMaxWidth().clickable { onSelect(if (selected == t.index) null else t.index) }) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(t.label, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        Text("Target: " + t.target)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (t.sensitivity != null) Metric("SENSITIVITY", fmt(t.sensitivity) + "%", Modifier.weight(1f))
                            if (t.specificity != null) Metric("SPECIFICITY", fmt(t.specificity) + "%", Modifier.weight(1f))
                        }
                        Text("Evidence " + t.grade + " · " + t.source, style = MaterialTheme.typography.labelSmall)
                        if (selected == t.index) {
                            Detail("When to use", t.whenToUse); Detail("Positive result", t.positive)
                            Detail("Negative result", t.negative); Detail("Limitations / sampling", t.caveat)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ReferenceScreen(p: PresentationData, selected: String?, onSelect: (String?) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Text("Clinical reference library", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text(p.diagnoses.size.toString() + " diagnosis profiles · " + p.contexts.size + " context modifiers · " + p.stopRules.size + " stop rules")
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), contentPadding = PaddingValues(bottom = 16.dp)) {
            items(p.diagnoses, key = { it.id }) { d ->
                Card(Modifier.fillMaxWidth().clickable { onSelect(if (selected == d.id) null else d.id) }) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                        Text(d.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        Text("Evidence " + d.grade + " · " + d.source, style = MaterialTheme.typography.labelSmall)
                        if (selected == d.id) DiagnosisDetails(d)
                    }
                }
            }
            if (p.contexts.isNotEmpty()) item { Text("Patient context modifiers", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold) }
            items(p.contexts, key = { "context-" + it.index }) { c ->
                Card {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(c.label, fontWeight = FontWeight.SemiBold)
                        c.ageRange?.let { Text("Age range: " + it.first + "–" + it.second) }
                        Text(c.multipliers.entries.joinToString(" · ") { it.key + ": ×" + fmt(it.value) })
                        Text("Grade " + c.grade + " · " + c.source, style = MaterialTheme.typography.labelSmall)
                        Text("Reference only; these modifiers are not applied to the ranking.", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}

@Composable
private fun DiagnosisDetails(d: PresentationDiagnosis) {
    Detail("Typical presentation", d.look)
    Detail("Features supporting diagnosis", d.supporting.joinToString("\n• ", "• "))
    Detail("Features arguing against", d.opposing.joinToString("\n• ", "• "))
    Detail("Clinical confirmation", d.clinicalFeatures)
    Detail("Dermoscopy", d.dermoscopy)
    Detail("Histopathology", d.histopathology)
    Detail("Associations", d.associations)
    Detail("Management reference", d.management)
    Detail("Typical sites", d.locations.joinToString(", "))
    Detail("Distribution", d.pattern)
}

@Composable
private fun Detail(title: String, body: String) {
    if (body.isNotBlank()) Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(title, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
        Text(body, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun Metric(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(value, style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ProbabilityBar(label: String, value: Double) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        if (label.isNotBlank()) Text(label, style = MaterialTheme.typography.bodyMedium)
        LinearProgressIndicator(progress = { value.coerceIn(0.0, 1.0).toFloat() },
            modifier = Modifier.fillMaxWidth().height(9.dp), strokeCap = androidx.compose.ui.graphics.StrokeCap.Round)
    }
}

@Composable
private fun Workflow(number: String, title: String, body: String) {
    Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Surface(shape = CircleShape, color = MaterialTheme.colorScheme.primaryContainer) {
            Text(number, Modifier.padding(10.dp), fontWeight = FontWeight.Bold)
        }
        Column(Modifier.weight(1f)) { Text(title, fontWeight = FontWeight.SemiBold); Text(body, style = MaterialTheme.typography.bodySmall) }
    }
}

@Composable
private fun EmptyCard(title: String, body: String) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text(body)
        }
    }
}

private fun fmt(v: Double) = String.format(Locale.US, "%.2f", v)
