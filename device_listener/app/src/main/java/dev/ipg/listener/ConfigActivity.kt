package dev.ipg.listener

import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class ConfigActivity : AppCompatActivity() {

    private lateinit var configFile: File
    private lateinit var statusText: TextView
    private lateinit var labelEdit: EditText
    private lateinit var searchEdit: EditText
    private lateinit var recycler: RecyclerView
    private lateinit var btnReset: Button
    private lateinit var btnSave: Button
    private lateinit var adapter: AppListAdapter

    /** Last value we auto-filled into [labelEdit]. Lets us know whether the
     *  user has manually edited it (in which case we won't overwrite). */
    private var lastAutoLabel: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_config)

        configFile = File(getExternalFilesDir(null) ?: filesDir, "config.json")

        statusText = findViewById(R.id.status)
        labelEdit = findViewById(R.id.appLabel)
        searchEdit = findViewById(R.id.search)
        recycler = findViewById(R.id.recycler)
        btnReset = findViewById(R.id.btnReset)
        btnSave = findViewById(R.id.btnSave)

        adapter = AppListAdapter { onSelectionChanged() }
        recycler.layoutManager = LinearLayoutManager(this)
        recycler.adapter = adapter

        loadApps()
        loadConfig()

        searchEdit.addTextChangedListener(object : SimpleTextWatcher() {
            override fun afterTextChanged(s: Editable?) {
                adapter.setSearch(s?.toString().orEmpty())
            }
        })

        labelEdit.addTextChangedListener(object : SimpleTextWatcher() {
            override fun afterTextChanged(s: Editable?) {
                updateStatus()
            }
        })

        btnReset.setOnClickListener { reset() }
        btnSave.setOnClickListener { save() }

        updateStatus()
    }

    private fun loadApps() {
        val pm = packageManager
        val items = try {
            pm.getInstalledApplications(PackageManager.GET_META_DATA)
                .map { info ->
                    AppItem(
                        packageName = info.packageName,
                        label = pm.getApplicationLabel(info).toString(),
                        icon = info.loadIcon(pm),
                        isSystem = info.flags and ApplicationInfo.FLAG_SYSTEM != 0,
                    )
                }
        } catch (t: Throwable) {
            Toast.makeText(this, "load apps failed: ${t.message}", Toast.LENGTH_LONG).show()
            emptyList()
        }
        adapter.setAllItems(items)
    }

    private fun loadConfig() {
        if (!configFile.exists()) return
        try {
            val json = JSONObject(configFile.readText(Charsets.UTF_8))
            val label = json.optString("appLabel")
            labelEdit.setText(label)
            lastAutoLabel = label
            val arr = json.optJSONArray("packages")
            val pkgs = if (arr == null) emptySet()
            else (0 until arr.length())
                .mapNotNull { arr.optString(it).takeIf { s -> s.isNotBlank() } }
                .toSet()
            adapter.setSelected(pkgs)
        } catch (t: Throwable) {
            Toast.makeText(this, "config parse failed: ${t.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun onSelectionChanged() {
        val current = labelEdit.text.toString()
        val selected = adapter.selectedPackages()
        if (current.isEmpty() || current == lastAutoLabel) {
            val first = selected.firstOrNull()
            val suggestion = first?.let {
                try {
                    val info = packageManager.getApplicationInfo(it, 0)
                    packageManager.getApplicationLabel(info).toString()
                } catch (_: Throwable) { null }
            } ?: ""
            lastAutoLabel = suggestion
            labelEdit.setText(suggestion)
        }
        updateStatus()
    }

    private fun updateStatus() {
        val n = adapter.selectedPackages().size
        val label = labelEdit.text.toString().trim().ifEmpty { "_filtered" }
        statusText.text = if (n == 0) {
            getString(R.string.cfg_no_filter)
        } else {
            "Active: $label ($n package${if (n != 1) "s" else ""})"
        }
    }

    private fun reset() {
        if (configFile.exists()) configFile.delete()
        labelEdit.setText("")
        lastAutoLabel = ""
        adapter.setSelected(emptySet())
        updateStatus()
        Toast.makeText(this, "Filter cleared", Toast.LENGTH_SHORT).show()
    }

    private fun save() {
        val label = labelEdit.text.toString().trim()
        val pkgs = adapter.selectedPackages()
        try {
            val json = JSONObject().apply {
                if (label.isNotEmpty()) put("appLabel", label)
                put("packages", JSONArray(pkgs.toList()))
            }
            configFile.parentFile?.mkdirs()
            configFile.writeText(json.toString(2), Charsets.UTF_8)
            val msg = if (pkgs.isEmpty()) "Saved (no filter — all packages)"
                else "Saved (${pkgs.size} pkg${if (pkgs.size != 1) "s" else ""})"
            Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
            updateStatus()
        } catch (t: Throwable) {
            Toast.makeText(this, "Save failed: ${t.message}", Toast.LENGTH_LONG).show()
        }
    }

    private abstract class SimpleTextWatcher : TextWatcher {
        override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
        override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
    }
}
