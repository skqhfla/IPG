package dev.ipg.listener

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var status: TextView
    private lateinit var filterStatus: TextView
    private lateinit var btnSettings: Button
    private lateinit var btnFilter: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        status = findViewById(R.id.status)
        filterStatus = findViewById(R.id.filterStatus)
        btnSettings = findViewById(R.id.btnSettings)
        btnFilter = findViewById(R.id.btnFilter)

        btnSettings.setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        btnFilter.setOnClickListener {
            startActivity(Intent(this, ConfigActivity::class.java))
        }
    }

    override fun onResume() {
        super.onResume()
        status.setText(
            if (isServiceEnabled()) R.string.status_enabled
            else R.string.status_disabled
        )
        filterStatus.text = renderFilterStatus()
    }

    private fun isServiceEnabled(): Boolean {
        val enabled = Settings.Secure.getString(
            contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
        ) ?: return false
        val expected = "$packageName/${IpgAccessibilityService::class.java.name}"
        return enabled.split(':').any { it.equals(expected, ignoreCase = true) }
    }

    private fun renderFilterStatus(): String {
        val configFile = File(getExternalFilesDir(null) ?: filesDir, "config.json")
        if (!configFile.exists()) {
            return buildString {
                append("Filter:  none (capture all packages)\n")
                append("Output:  flat → device_listener/captures/")
            }
        }
        val (label, packages) = try {
            val json = JSONObject(configFile.readText(Charsets.UTF_8))
            val lbl = json.optString("appLabel").takeIf { it.isNotBlank() }
            val arr = json.optJSONArray("packages")
            val pkgs = if (arr == null) emptyList()
            else (0 until arr.length()).mapNotNull {
                arr.optString(it).takeIf { s -> s.isNotBlank() }
            }
            lbl to pkgs
        } catch (t: Throwable) {
            return "Filter:  config.json parse error\n         ${t.message}"
        }

        if (packages.isEmpty()) {
            return buildString {
                append("Filter:  config exists but no packages\n")
                append("Output:  flat → device_listener/captures/")
            }
        }

        val resolvedLabel = label ?: "_filtered"
        return buildString {
            append("Filter:  ")
            append(resolvedLabel)
            append(" (")
            append(packages.size)
            append(if (packages.size == 1) " pkg)\n" else " pkgs)\n")
            packages.take(MAX_PKGS_LISTED).forEach { pkg ->
                append("  • ")
                append(pkg)
                append('\n')
            }
            if (packages.size > MAX_PKGS_LISTED) {
                append("  … +")
                append(packages.size - MAX_PKGS_LISTED)
                append(" more\n")
            }
            append("Output:  IPG → outputs_APK/")
            append(resolvedLabel)
            append('/')
        }
    }

    companion object {
        private const val MAX_PKGS_LISTED = 5
    }
}
