package co.fallsoft.losangelex

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.installations.FirebaseInstallations

class MainActivity : ComponentActivity() {
    private val model: RoomViewModel by viewModels()
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
        if (FirebaseApp.initializeApp(this) != null) {
            FirebaseMessaging.getInstance().register().continueWithTask { registration ->
                if (!registration.isSuccessful) throw checkNotNull(registration.exception)
                FirebaseInstallations.getInstance().id
            }.addOnSuccessListener { fid ->
                getSharedPreferences("push", MODE_PRIVATE).edit().putString("fid", fid).apply()
                model.syncPush()
            }
        }
        openNotification(intent)
        setContent {
            MaterialTheme(colorScheme = RoomColors) {
                val state by model.state.collectAsStateWithLifecycle()
                RoomScreen(state, model.repository.credentials.url, model::connect, model::draft,
                    { model.send() }, model::focus, { model.answer(it) }, { event, decision -> model.approve(event, decision) }, { model.stop() }, history = model.history, cancelReply = model::cancelReply,
                    selectTask = model::selectTask, latest = model::latest)
            }
        }
    }
    override fun onStart() { super.onStart(); model.foreground(true) }
    override fun onStop() { model.foreground(false); super.onStop() }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        openNotification(intent)
    }

    private fun openNotification(intent: Intent) {
        val device = intent.getStringExtra("deviceId") ?: return
        val registered = getSharedPreferences("push", MODE_PRIVATE)
            .getString("deviceId:${model.repository.credentials.url}", null)
        if (device == registered) intent.getStringExtra("attentionId")?.let(model::openAttention)
    }
}
