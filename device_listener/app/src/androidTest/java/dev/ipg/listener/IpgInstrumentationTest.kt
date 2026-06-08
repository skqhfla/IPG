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
import android.view.accessibility.AccessibilityWindowInfo
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
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.ThreadFactory
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
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
        try {
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
        } finally {
            handler.shutdown()
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
    // IME(소프트 키보드) 가시성. AccessibilityWindowInfo.TYPE_INPUT_METHOD 윈도우의
    // 존재로 판정 → ROM 의존 클래스명 패턴 매칭 없이도 정확. 상태 바뀔 때만 한 줄
    // emit (IME_VISIBLE / IME_HIDDEN) 해서 host(a11y_event_listener) 가 캐시.
    @Volatile private var lastImeVisible: Boolean = false
    private var configMtime = 0L
    // dumpExecutor 가 백그라운드 스레드에서 resolveOutputs() 통해 읽으므로 @Volatile.
    @Volatile private var configPackages: Set<String>? = null
    @Volatile private var configAppLabel: String? = null

    // dumpHierarchy + captureScreenshot 은 한 사이클이 1-2s 걸리는 무거운 작업.
    // a11y 콜백 스레드에서 인라인 실행하면 swipe 직후 WINDOW_CONTENT_CHANGED 폭주에
    // 큐가 막혀 VIEW_SCROLLED 도 줄 끝에 갇히는 회귀가 있었다. 단일 worker 스레드 +
    // 작은 bounded queue + DiscardOldestPolicy 로 옮겨, 콜백 스레드는 emit 만 하고
    // 즉시 return. burst 가 너무 길면 가장 오래된 (이미 stale 한) dump 부터 자연
    // drop — 어차피 swipe 도중 N-1개 중간 프레임은 final 프레임이 오면 의미 없음.
    private val dumpExecutor: ThreadPoolExecutor = ThreadPoolExecutor(
        1, 1,
        0L, TimeUnit.MILLISECONDS,
        LinkedBlockingQueue<Runnable>(DUMP_QUEUE_CAPACITY),
        ThreadFactory { r -> Thread(r, "ipg-dump").apply { isDaemon = true } },
        ThreadPoolExecutor.DiscardOldestPolicy(),
    )

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
        // host 가 connect 시점에 정확한 IME 상태를 알 수 있게 한 번 seed.
        maybeEmitImeState()
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

    /**
     * AccessibilityWindowInfo.TYPE_INPUT_METHOD 윈도우가 현재 떠 있으면 true.
     * UiAutomation.getWindows() 가 윈도우 type 메타데이터를 직접 주므로 ROM 별
     * IME 클래스명 패턴 매칭 없이도 정확. listener 콜백 스레드에서만 호출되며
     * 한 dump 사이클(<1ms) 이내로 종료.
     */
    private fun isImeWindowVisible(): Boolean {
        return try {
            ui.windows?.any { w ->
                try { w.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }
                catch (_: Throwable) { false }
            } == true
        } catch (_: Throwable) {
            false
        }
    }

    /** IME 가시성 transition 만 한 줄 emit. 상태 변화 없으면 noop. */
    private fun maybeEmitImeState() {
        val visible = isImeWindowVisible()
        if (visible == lastImeVisible) return
        lastImeVisible = visible
        emit(JSONObject().apply {
            put("ts", System.currentTimeMillis())
            put("type", if (visible) "IME_VISIBLE" else "IME_HIDDEN")
            put("session", sessionId)
        })
    }

    fun handle(event: AccessibilityEvent) {
        maybeReloadConfig()

        val type = event.eventType
        val pkg = event.packageName?.toString().orEmpty()

        // IME 상태 변화는 보통 WINDOW_STATE_CHANGED 또는 WINDOWS_CHANGED 와 동반
        // 발생. 매 이벤트마다 windows 조회는 비싸므로 두 타입만 검사.
        if (type == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
            || type == AccessibilityEvent.TYPE_WINDOWS_CHANGED) {
            maybeEmitImeState()
        }

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

            addEventPayload(event, type, cls, this)

            captureSourceInto(event, this)
        }

        emit(eventJson)
        // VIEW_SCROLLED 는 host 의 wait_for_scroll_evt 가 event payload(scrollX/dy/idx
        // 등) 만 소비하므로 hierarchy XML + screenshot 까지 만들 필요가 없다 — skip.
        // 나머지 타입은 dumpExecutor 큐에 enqueue → 콜백 스레드는 즉시 return 해서
        // 다음 a11y 이벤트 대기. dumpExecutor 가 단일 worker 라 dump 순서는 보존되고,
        // 큐가 가득 차면 DiscardOldestPolicy 가 가장 오래된 stale dump 부터 drop.
        if (type != AccessibilityEvent.TYPE_VIEW_SCROLLED) {
            dumpExecutor.execute {
                try {
                    dumpHierarchy(ts, typeName, eventJson)
                } catch (t: Throwable) {
                    Log.w(TAG, "bg dump failed: ${t.message}")
                }
            }
        }
    }

    fun shutdown() {
        try {
            dumpExecutor.shutdownNow()
        } catch (_: Throwable) {}
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
        attr(sb, "visible-to-user", node.isVisibleToUser.toString())
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
        AccessibilityEvent.TYPE_VIEW_CLICKED -> "VIEW_CLICKED"
        AccessibilityEvent.TYPE_VIEW_LONG_CLICKED -> "VIEW_LONG_CLICKED"
        AccessibilityEvent.TYPE_VIEW_SELECTED -> "VIEW_SELECTED"
        AccessibilityEvent.TYPE_VIEW_FOCUSED -> "VIEW_FOCUSED"
        AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED -> "VIEW_TEXT_CHANGED"
        AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> "WINDOW_STATE_CHANGED"
        AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED -> "NOTIFICATION_STATE_CHANGED"
        AccessibilityEvent.TYPE_VIEW_HOVER_ENTER -> "VIEW_HOVER_ENTER"
        AccessibilityEvent.TYPE_VIEW_HOVER_EXIT -> "VIEW_HOVER_EXIT"
        AccessibilityEvent.TYPE_TOUCH_EXPLORATION_GESTURE_START -> "TOUCH_EXPLORATION_GESTURE_START"
        AccessibilityEvent.TYPE_TOUCH_EXPLORATION_GESTURE_END -> "TOUCH_EXPLORATION_GESTURE_END"
        AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> "WINDOW_CONTENT_CHANGED"
        AccessibilityEvent.TYPE_VIEW_SCROLLED -> "VIEW_SCROLLED"
        AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED -> "VIEW_TEXT_SELECTION_CHANGED"
        AccessibilityEvent.TYPE_ANNOUNCEMENT -> "ANNOUNCEMENT"
        AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUSED -> "VIEW_ACCESSIBILITY_FOCUSED"
        AccessibilityEvent.TYPE_VIEW_ACCESSIBILITY_FOCUS_CLEARED -> "VIEW_ACCESSIBILITY_FOCUS_CLEARED"
        AccessibilityEvent.TYPE_VIEW_TEXT_TRAVERSED_AT_MOVEMENT_GRANULARITY -> "VIEW_TEXT_TRAVERSED_AT_MOVEMENT_GRANULARITY"
        AccessibilityEvent.TYPE_GESTURE_DETECTION_START -> "GESTURE_DETECTION_START"
        AccessibilityEvent.TYPE_GESTURE_DETECTION_END -> "GESTURE_DETECTION_END"
        AccessibilityEvent.TYPE_TOUCH_INTERACTION_START -> "TOUCH_INTERACTION_START"
        AccessibilityEvent.TYPE_TOUCH_INTERACTION_END -> "TOUCH_INTERACTION_END"
        AccessibilityEvent.TYPE_WINDOWS_CHANGED -> "WINDOWS_CHANGED"
        AccessibilityEvent.TYPE_VIEW_CONTEXT_CLICKED -> "VIEW_CONTEXT_CLICKED"
        AccessibilityEvent.TYPE_ASSIST_READING_CONTEXT -> "ASSIST_READING_CONTEXT"
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

    /** Emit every AccessibilityEvent payload field that carries signal.
     *  Index/scroll fields use -1 (AccessibilityRecord.UNDEFINED) as "unset" and
     *  are omitted when unset; boolean properties are emitted only when true. */
    private fun addEventPayload(
        event: AccessibilityEvent,
        type: Int,
        cls: String,
        into: JSONObject,
    ) {
        into.put("eventTime", event.eventTime)
        if (event.windowId != -1) into.put("windowId", event.windowId)
        if (event.action != 0) into.put("action", event.action)
        if (event.movementGranularity != 0) into.put("movementGranularity", event.movementGranularity)

        val cd = event.contentDescription?.toString().orEmpty().take(TEXT_MAX)
        if (cd.isNotEmpty()) into.put("contentDesc", cd)
        val before = event.beforeText?.toString().orEmpty().take(TEXT_MAX)
        if (before.isNotEmpty()) into.put("beforeText", before)

        // VIEW_SCROLLED keeps emitting its fields unconditionally (even -1) so the
        // host's scroll-exhaustion heuristic in loop.py sees the same shape as before.
        val scrolled = type == AccessibilityEvent.TYPE_VIEW_SCROLLED
        if (scrolled || event.fromIndex != -1) into.put("fromIndex", event.fromIndex)
        if (scrolled || event.toIndex != -1) into.put("toIndex", event.toIndex)
        if (event.currentItemIndex != -1) into.put("currentItemIndex", event.currentItemIndex)
        if (scrolled || event.itemCount != -1) into.put("itemCount", event.itemCount)
        if (event.addedCount != -1) into.put("addedCount", event.addedCount)
        if (event.removedCount != -1) into.put("removedCount", event.removedCount)

        if (scrolled || event.scrollX != -1) into.put("scrollX", event.scrollX)
        if (scrolled || event.scrollY != -1) into.put("scrollY", event.scrollY)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (scrolled || event.scrollDeltaX != -1) into.put("scrollDeltaX", event.scrollDeltaX)
            if (scrolled || event.scrollDeltaY != -1) into.put("scrollDeltaY", event.scrollDeltaY)
            if (scrolled || event.maxScrollX != -1) into.put("maxScrollX", event.maxScrollX)
            if (scrolled || event.maxScrollY != -1) into.put("maxScrollY", event.maxScrollY)
        }

        val props = mutableListOf<String>()
        if (event.isEnabled) props += "enabled"
        if (event.isChecked) props += "checked"
        if (event.isPassword) props += "password"
        if (event.isFullScreen) props += "fullScreen"
        if (event.isScrollable) props += "scrollable"
        if (props.isNotEmpty()) into.put("props", props.joinToString("|"))

        val change = contentChangeFlags(event.contentChangeTypes)
        if (change.isNotEmpty()) into.put("change", change)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            val wc = windowChangeFlags(event.windowChanges)
            if (wc.isNotEmpty()) into.put("windowChanges", wc)
        }

        if (event.recordCount > 0) into.put("recordCount", event.recordCount)

        if (type == AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED) {
            into.put("isToast", cls.contains("android.widget.Toast"))
        }
    }

    private fun windowChangeFlags(flags: Int): String {
        if (flags == 0) return ""
        val parts = mutableListOf<String>()
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_ADDED != 0) parts += "ADDED"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_REMOVED != 0) parts += "REMOVED"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_TITLE != 0) parts += "TITLE"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_BOUNDS != 0) parts += "BOUNDS"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_LAYER != 0) parts += "LAYER"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_ACTIVE != 0) parts += "ACTIVE"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_FOCUSED != 0) parts += "FOCUSED"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_ACCESSIBILITY_FOCUSED != 0) parts += "A11Y_FOCUSED"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_PARENT != 0) parts += "PARENT"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_CHILDREN != 0) parts += "CHILDREN"
        if (flags and AccessibilityEvent.WINDOWS_CHANGE_PIP != 0) parts += "PIP"
        return parts.joinToString("|")
    }

    companion object {
        private const val TAG = "IPG_EVT"
        private const val CONTENT_DEBOUNCE_MS = 300L
        private const val TEXT_MAX = 500
        // dumpExecutor 큐 상한. 한 dump 가 ~1s 라 8개면 swipe 직후 burst 정도는
        // 자연 흡수, 그 이상 쌓이면 어차피 사용자 화면에 의미 있는 시점이 지나
        // stale 한 dump 들이라 DiscardOldestPolicy 로 자동 drop.
        private const val DUMP_QUEUE_CAPACITY = 8
    }
}
