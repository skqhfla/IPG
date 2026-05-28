package dev.ipg.listener

import android.app.UiAutomation
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Build
import android.util.Log
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger

/**
 * Maestro-style listener.
 *
 * Runs as an instrumented test under `am instrument -w` — the test process gets
 * shell-level UiAutomation access, bypassing the AccessibilityService binding
 * path (which Samsung Knox refuses for sideloaded APKs).
 *
 * The host launches us with:
 *   adb shell am instrument -w -m \
 *     -e class dev.ipg.listener.IpgInstrumentationTest#run \
 *     dev.ipg.listener.test/androidx.test.runner.AndroidJUnitRunner
 *
 * Output identical to the old AccessibilityService:
 *   - logcat tag IPG_EVT, one JSON per line
 *   - XML/JSON/PNG dumps under the same paths consumed by dump_collector.py
 */
@RunWith(AndroidJUnit4::class)
class IpgInstrumentationTest {

    @Test
    fun run() {
        val instr = InstrumentationRegistry.getInstrumentation()
        val ctx: Context = instr.targetContext
        // Bootstrap UiDevice first — its constructor wires up UiAutomation in a way
        // that subsequent `instr.uiAutomation` reads return the same instance,
        // matching Maestro's pattern. Avoids "UiAutomationService already registered".
        UiDevice.getInstance(instr)
        val ui: UiAutomation = instr.uiAutomation

        val handler = EventHandler(ctx, ui)
        handler.emitConnected()

        ui.setOnAccessibilityEventListener { event ->
            try {
                handler.handle(event)
            } catch (t: Throwable) {
                Log.w(TAG, "handler error: ${t.message}")
            }
        }

        // The old AccessibilityService had a BroadcastReceiver for DUMP_NOW.
        // Instrumented tests can't register exported receivers reliably; instead
        // we poll a sentinel file the host can `touch` to request an on-demand dump.
        val triggerFile = handler.triggerFile()
        while (!Thread.currentThread().isInterrupted) {
            try {
                if (triggerFile.exists()) {
                    try { triggerFile.delete() } catch (_: Throwable) {}
                    try {
                        handler.manualDump()
                    } catch (t: Throwable) {
                        Log.w(TAG, "manual dump failed: ${t.message}")
                    }
                }
                Thread.sleep(TRIGGER_POLL_MS)
            } catch (_: InterruptedException) {
                break
            }
        }
    }

    companion object {
        private const val TAG = "IPG_EVT"
        private const val TRIGGER_POLL_MS = 100L
    }
}

private class EventHandler(private val ctx: Context, private val ui: UiAutomation) {

    private val sessionId: String =
        SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
    private val captureBaseDir: File = ctx.getExternalFilesDir(null) ?: ctx.filesDir
    private val configFile: File = File(captureBaseDir, "config.json")
    private val seqCounter = AtomicInteger(0)
    private val lastContentChanged = HashMap<String, Long>()

    @Volatile private var lastWindowClass: String = ""
    private var configMtime = 0L
    private var configPackages: Set<String>? = null
    private var configAppLabel: String? = null

    fun emitConnected() {
        maybeReloadConfig()
        emit(JSONObject().apply {
            put("ts", System.currentTimeMillis())
            put("type", "SERVICE_CONNECTED")
            put("session", sessionId)
            put("apiLevel", Build.VERSION.SDK_INT)
            put("screenshotMode", "uiautomation")
            put("configFile", configFile.absolutePath)
            put("triggerFile", triggerFile().absolutePath)
            put("appLabel", configAppLabel ?: JSONObject.NULL)
            val pkgs = configPackages
            if (pkgs != null) put("packagesFilter", org.json.JSONArray(pkgs.toList()))
        })
    }

    fun triggerFile(): File = File(captureBaseDir, "dump_now.trigger")

    /** Snapshot the current screen regardless of any event filter / debounce.
     *  Bypasses package filter — the host explicitly asked for it. */
    fun manualDump() {
        val ts = System.currentTimeMillis()
        val triggerJson = JSONObject().apply {
            put("ts", ts)
            put("type", "MANUAL_DUMP")
            put("pkg", "<trigger>")
        }
        emit(triggerJson)
        dumpHierarchy(ts, "MANUAL_DUMP", triggerJson)
    }

    fun handle(event: AccessibilityEvent) {
        maybeReloadConfig()

        val type = event.eventType
        val pkg = event.packageName?.toString().orEmpty()

        val filter = configPackages
        if (filter != null && filter.isNotEmpty() && pkg !in filter) return

        val cls = event.className?.toString().orEmpty()

        if (type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED && cls.isNotEmpty()) {
            lastWindowClass = cls
        }

        if (type == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED) {
            val key = "$pkg|$cls|${event.contentChangeTypes}"
            val now = System.currentTimeMillis()
            val last = lastContentChanged[key] ?: 0L
            if (now - last < CONTENT_DEBOUNCE_MS) return
            lastContentChanged[key] = now
        }

        val ts = System.currentTimeMillis()
        val typeName = eventTypeName(type)

        val eventJson = JSONObject().apply {
            put("ts", ts)
            put("type", typeName)
            put("pkg", pkg)
            if (cls.isNotEmpty()) put("class", cls)

            val text = event.text
                ?.joinToString(" | ") { it?.toString().orEmpty() }
                .orEmpty()
                .take(TEXT_MAX)
            if (text.isNotEmpty()) put("text", text)

            when (type) {
                AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> {
                    val flags = contentChangeFlags(event.contentChangeTypes)
                    if (flags.isNotEmpty()) put("change", flags)
                }
                AccessibilityEvent.TYPE_VIEW_SCROLLED -> {
                    put("scrollX", event.scrollX)
                    put("scrollY", event.scrollY)
                    put("fromIndex", event.fromIndex)
                    put("toIndex", event.toIndex)
                    put("itemCount", event.itemCount)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                        put("scrollDeltaX", event.scrollDeltaX)
                        put("scrollDeltaY", event.scrollDeltaY)
                        put("maxScrollX", event.maxScrollX)
                        put("maxScrollY", event.maxScrollY)
                    }
                }
                AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED -> {
                    put("isToast", cls.contains("android.widget.Toast"))
                }
            }

            captureSourceInto(event, this)
        }

        emit(eventJson)
        dumpHierarchy(ts, typeName, eventJson)
    }

    private fun maybeReloadConfig() {
        val f = configFile
        if (!f.exists()) {
            if (configPackages != null || configAppLabel != null) {
                configPackages = null
                configAppLabel = null
                configMtime = 0L
                Log.i(TAG, "config removed; capture all packages, flat mode")
            }
            return
        }
        val m = f.lastModified()
        if (m == configMtime && configMtime != 0L) return
        try {
            val json = JSONObject(f.readText(Charsets.UTF_8))
            val arr = json.optJSONArray("packages")
            configPackages = if (arr == null || arr.length() == 0) {
                null
            } else {
                (0 until arr.length())
                    .mapNotNull { arr.optString(it).takeIf { s -> s.isNotBlank() } }
                    .toSet()
            }
            val lbl = json.optString("appLabel")
            configAppLabel = if (lbl.isBlank()) null else lbl
            configMtime = m
            Log.i(TAG, "config reloaded: appLabel=$configAppLabel packages=$configPackages")
        } catch (t: Throwable) {
            Log.w(TAG, "config reload failed: ${t.message}")
        }
    }

    private data class OutputPaths(
        val mode: String,
        val appLabel: String?,
        val xml: File,
        val json: File,
        val screenshot: File,
    )

    private fun resolveOutputs(seq: Int, ts: Long, typeName: String): OutputPaths {
        val seqStr = String.format(Locale.US, "%06d", seq)
        val filter = configPackages
        if (filter != null && filter.isNotEmpty()) {
            val appLabel = configAppLabel ?: "_filtered"
            val base = File(captureBaseDir, "captures/$appLabel/$sessionId")
            val xmlDir = File(base, "xml").apply { mkdirs() }
            val screenDir = File(base, "screen").apply { mkdirs() }
            val jsonDir = File(base, "json").apply { mkdirs() }
            return OutputPaths(
                mode = "ipg",
                appLabel = appLabel,
                xml = File(xmlDir, "$seqStr.xml"),
                json = File(jsonDir, "$seqStr.json"),
                screenshot = File(screenDir, "$seqStr.png"),
            )
        }
        val base = File(captureBaseDir, "dumps/$sessionId").apply { mkdirs() }
        val baseName = String.format(Locale.US, "%06d_%d_%s", seq, ts, typeName)
        return OutputPaths(
            mode = "flat",
            appLabel = null,
            xml = File(base, "$baseName.xml"),
            json = File(base, "$baseName.json"),
            screenshot = File(base, "$baseName.png"),
        )
    }

    private fun captureSourceInto(event: AccessibilityEvent, into: JSONObject) {
        val source = try { event.source } catch (_: Throwable) { null } ?: return
        try {
            val rect = Rect()
            source.getBoundsInScreen(rect)
            val srcJson = JSONObject().apply {
                put("bounds", "[${rect.left},${rect.top}][${rect.right},${rect.bottom}]")
                val rid = source.viewIdResourceName
                if (!rid.isNullOrEmpty()) put("resourceId", rid)
                val cn = source.className?.toString()
                if (!cn.isNullOrEmpty()) put("class", cn)
                val txt = source.text?.toString().orEmpty().take(TEXT_MAX)
                if (txt.isNotEmpty()) put("text", txt)
                val cd = source.contentDescription?.toString().orEmpty().take(TEXT_MAX)
                if (cd.isNotEmpty()) put("contentDesc", cd)
            }
            into.put("source", srcJson)
        } finally {
            @Suppress("DEPRECATION")
            try { source.recycle() } catch (_: Throwable) {}
        }
    }

    private fun dumpHierarchy(ts: Long, typeName: String, eventJson: JSONObject) {
        val xml = try {
            buildHierarchyXml()
        } catch (t: Throwable) {
            Log.w(TAG, "dump build failed: ${t.message}")
            null
        } ?: return

        val seq = seqCounter.incrementAndGet()
        val paths = resolveOutputs(seq, ts, typeName)

        try {
            paths.xml.writeText(xml, Charsets.UTF_8)

            val sidecar = JSONObject(eventJson.toString()).apply {
                put("seq", seq)
                put("session", sessionId)
                put("xml", paths.xml.absolutePath)
                if (paths.appLabel != null) put("appLabel", paths.appLabel)
            }
            paths.json.writeText(sidecar.toString(2), Charsets.UTF_8)

            emit(JSONObject().apply {
                put("ts", ts)
                put("type", "DUMP_WRITTEN")
                put("session", sessionId)
                put("seq", seq)
                put("trigger", typeName)
                put("xml", paths.xml.absolutePath)
                put("meta", paths.json.absolutePath)
                put("screenshotMode", "uiautomation")
                put("outputMode", paths.mode)
                if (paths.appLabel != null) put("appLabel", paths.appLabel)
                put("screenshot", paths.screenshot.absolutePath)
            })

            captureScreenshot(seq, paths.screenshot)
        } catch (t: Throwable) {
            Log.w(TAG, "dump write failed: ${t.message}")
        }
    }

    private fun captureScreenshot(seq: Int, pngFile: File) {
        val bmp: Bitmap? = try {
            ui.takeScreenshot()
        } catch (t: Throwable) {
            Log.w(TAG, "takeScreenshot dispatch failed (seq=$seq): ${t.message}")
            emitScreenshotFailure(seq, "dispatch: ${t.message}")
            return
        }
        if (bmp == null) {
            emitScreenshotFailure(seq, "uiautomation returned null bitmap")
            return
        }
        try {
            pngFile.parentFile?.mkdirs()
            FileOutputStream(pngFile).use { out ->
                bmp.compress(Bitmap.CompressFormat.PNG, 100, out)
            }
            emit(JSONObject().apply {
                put("ts", System.currentTimeMillis())
                put("type", "DUMP_SCREENSHOT")
                put("session", sessionId)
                put("seq", seq)
                put("path", pngFile.absolutePath)
            })
        } catch (t: Throwable) {
            Log.w(TAG, "screenshot save failed (seq=$seq): ${t.message}")
            emitScreenshotFailure(seq, "save: ${t.message}")
        } finally {
            try { bmp.recycle() } catch (_: Throwable) {}
        }
    }

    private fun emitScreenshotFailure(seq: Int, reason: String) {
        emit(JSONObject().apply {
            put("ts", System.currentTimeMillis())
            put("type", "DUMP_SCREENSHOT_FAILED")
            put("session", sessionId)
            put("seq", seq)
            put("reason", reason)
        })
    }

    private fun buildHierarchyXml(): String? {
        val root = ui.rootInActiveWindow ?: return null
        val rotation = try {
            val wm = ctx.getSystemService(Context.WINDOW_SERVICE) as WindowManager
            @Suppress("DEPRECATION")
            wm.defaultDisplay.rotation
        } catch (_: Throwable) {
            0
        }
        val sb = StringBuilder(8192)
        sb.append("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n")
        sb.append("<hierarchy")
        attr(sb, "rotation", rotation.toString())
        attr(sb, "window-id", root.windowId.toString())
        attr(sb, "package", root.packageName?.toString().orEmpty())
        attr(sb, "activity", lastWindowClass)
        sb.append(">\n")
        try {
            walkNode(root, 0, sb)
        } finally {
            @Suppress("DEPRECATION")
            try { root.recycle() } catch (_: Throwable) {}
        }
        sb.append("</hierarchy>\n")
        return sb.toString()
    }

    private fun walkNode(node: AccessibilityNodeInfo?, index: Int, sb: StringBuilder) {
        if (node == null) return
        val rect = Rect()
        node.getBoundsInScreen(rect)

        sb.append("<node")
        attr(sb, "index", index.toString())
        attr(sb, "text", node.text?.toString().orEmpty())
        attr(sb, "resource-id", node.viewIdResourceName.orEmpty())
        attr(sb, "class", node.className?.toString().orEmpty())
        attr(sb, "package", node.packageName?.toString().orEmpty())
        attr(sb, "content-desc", node.contentDescription?.toString().orEmpty())
        attr(sb, "checkable", node.isCheckable.toString())
        attr(sb, "checked", node.isChecked.toString())
        attr(sb, "clickable", node.isClickable.toString())
        attr(sb, "enabled", node.isEnabled.toString())
        attr(sb, "focusable", node.isFocusable.toString())
        attr(sb, "focused", node.isFocused.toString())
        attr(sb, "scrollable", node.isScrollable.toString())
        attr(sb, "long-clickable", node.isLongClickable.toString())
        attr(sb, "password", node.isPassword.toString())
        attr(sb, "selected", node.isSelected.toString())
        attr(sb, "important-for-accessibility", node.isImportantForAccessibility.toString())
        attr(sb, "bounds", "[${rect.left},${rect.top}][${rect.right},${rect.bottom}]")

        val childCount = node.childCount
        if (childCount == 0) {
            sb.append(" />\n")
        } else {
            sb.append(">\n")
            for (i in 0 until childCount) {
                val child = node.getChild(i)
                walkNode(child, i, sb)
                if (child != null) {
                    @Suppress("DEPRECATION")
                    try { child.recycle() } catch (_: Throwable) {}
                }
            }
            sb.append("</node>\n")
        }
    }

    private fun attr(sb: StringBuilder, name: String, value: String) {
        sb.append(' ').append(name).append("=\"").append(escAttr(value)).append('"')
    }

    private fun escAttr(s: String): String {
        if (s.isEmpty()) return s
        val out = StringBuilder(s.length)
        for (c in s) {
            when (c) {
                '&' -> out.append("&amp;")
                '<' -> out.append("&lt;")
                '>' -> out.append("&gt;")
                '"' -> out.append("&quot;")
                else -> {
                    val code = c.code
                    if (code < 0x20 && c != '\n' && c != '\t' && c != '\r') {
                        // skip XML-illegal control chars
                    } else {
                        out.append(c)
                    }
                }
            }
        }
        return out.toString()
    }

    private fun emit(json: JSONObject) {
        Log.i(TAG, json.toString())
    }

    private fun eventTypeName(t: Int): String = when (t) {
        AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> "WINDOW_STATE_CHANGED"
        AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> "WINDOW_CONTENT_CHANGED"
        AccessibilityEvent.TYPE_VIEW_SCROLLED -> "VIEW_SCROLLED"
        AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED -> "NOTIFICATION_STATE_CHANGED"
        AccessibilityEvent.TYPE_VIEW_CLICKED -> "VIEW_CLICKED"
        else -> "OTHER_$t"
    }

    private fun contentChangeFlags(flags: Int): String {
        if (flags == 0) return ""
        val parts = mutableListOf<String>()
        if (flags and AccessibilityEvent.CONTENT_CHANGE_TYPE_SUBTREE != 0) parts += "SUBTREE"
        if (flags and AccessibilityEvent.CONTENT_CHANGE_TYPE_TEXT != 0) parts += "TEXT"
        if (flags and AccessibilityEvent.CONTENT_CHANGE_TYPE_CONTENT_DESCRIPTION != 0) parts += "DESC"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (flags and AccessibilityEvent.CONTENT_CHANGE_TYPE_PANE_TITLE != 0) parts += "PANE_TITLE"
            if (flags and AccessibilityEvent.CONTENT_CHANGE_TYPE_PANE_APPEARED != 0) parts += "PANE_APPEARED"
            if (flags and AccessibilityEvent.CONTENT_CHANGE_TYPE_PANE_DISAPPEARED != 0) parts += "PANE_DISAPPEARED"
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            if (flags and AccessibilityEvent.CONTENT_CHANGE_TYPE_STATE_DESCRIPTION != 0) parts += "STATE"
        }
        return parts.joinToString("|")
    }

    companion object {
        private const val TAG = "IPG_EVT"
        private const val CONTENT_DEBOUNCE_MS = 300L
        private const val TEXT_MAX = 500
    }
}
