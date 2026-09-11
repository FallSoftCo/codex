package co.fallsoft.losangelex

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/** Push carries an opaque attention ID; current authorized content is fetched from the host. */
class RoomMessagingService : FirebaseMessagingService() {
    override fun onMessageReceived(message: RemoteMessage) {
        val attention = message.data["attentionId"] ?: return
        val device = message.data["deviceId"] ?: return
        val push = getSharedPreferences("push", MODE_PRIVATE)
        if (device != push.getString("deviceId:${Credentials(this).url}", null)) return
        push.edit().putString("lastDeviceId", device)
            .putLong("lastReceivedAt", System.currentTimeMillis()).putString("lastAttentionId", attention)
            .putInt("lastPriority", message.priority).putInt("lastOriginalPriority", message.originalPriority)
            .putLong("lastSentAt", message.sentTime).apply()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("attention", "Needs your attention", NotificationManager.IMPORTANCE_HIGH))
        val intent = Intent(this, MainActivity::class.java).putExtra("attentionId", attention)
            .putExtra("deviceId", device).setData(Uri.parse("losangelex://attention/$device/$attention"))
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pending = PendingIntent.getActivity(this, attention.hashCode(), intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = android.app.Notification.Builder(this, "attention")
            .setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("Losangelex")
            .setContentText("A task needs your attention").setVisibility(android.app.Notification.VISIBILITY_PRIVATE)
            .setContentIntent(pending).setAutoCancel(true).setOnlyAlertOnce(true).build()
        if (manager.areNotificationsEnabled()) manager.notify(attention, 0, notification)
    }
    override fun onRegistered(installationId: String) {
        getSharedPreferences("push", MODE_PRIVATE).edit().putString("fid", installationId).apply()
        // Registration is reconciled by the authenticated foreground connection.
    }
}
