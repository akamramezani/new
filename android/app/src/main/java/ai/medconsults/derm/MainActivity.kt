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

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { DermatologyApp() } }
    }
}

@Composable
private fun DermatologyApp() {
    val presentations = listOf(
        "Scaly", "Acute", "Bulla", "Wheal", "Purpura", "Eczema",
        "Annular", "Pigmented", "Facial", "Hair", "Nodular", "Hypopigmented"
    )
    var selected by remember { mutableStateOf<String?>(null) }

    Scaffold { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Text("MedConsults", style = MaterialTheme.typography.headlineMedium)
            Text("Dermatology Differential Engine", style = MaterialTheme.typography.titleLarge)
            Text("Shortlist · Discriminate · Confirm", style = MaterialTheme.typography.bodyLarge)
            HorizontalDivider()
            Text("Select a clinical presentation", style = MaterialTheme.typography.titleMedium)
            presentations.forEach { item ->
                FilterChip(
                    selected = selected == item,
                    onClick = { selected = item },
                    label = { Text(item) }
                )
            }
            if (selected != null) {
                Text("Selected: $selected", style = MaterialTheme.typography.titleMedium)
                Text("The presentation-specific finding list and offline scoring engine will be connected after the verified knowledge package is installed.")
            }
            HorizontalDivider()
            Text(
                "Clinical decision support only. Not a diagnosis and not a substitute for clinical examination, histopathology, or professional judgment.",
                style = MaterialTheme.typography.bodySmall
            )
        }
    }
}
