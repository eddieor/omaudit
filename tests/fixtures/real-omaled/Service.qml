import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root

  property var shell: null
  property string omarchyPath: ""
  property var manifest: null

  readonly property string pluginId: manifest && manifest.id ? String(manifest.id) : "b.omaled"
  readonly property var pluginSettings: currentSettings()
  readonly property var bar: shell && shell.bar ? shell.bar : null
  readonly property bool effectEnabled: setting("enabled", true) !== false
  readonly property real shadeOpacity: clamp(Number(setting("opacity", 0.65)), 0, 1)
  readonly property bool barSupportsContentDim: bar
    && ("barHovered" in bar)
    && ("moduleSlots" in bar)
  readonly property bool barTransparent: bar
    && ((("requestedTransparent" in bar) && bar.requestedTransparent === true)
      || (("transparent" in bar) && bar.transparent === true))
  readonly property bool barHidden: bar && ("barHidden" in bar) && bar.barHidden === true
  readonly property bool barHovered: barSupportsContentDim && bar.barHovered === true
  readonly property var barModuleSlots: barSupportsContentDim && Array.isArray(bar.moduleSlots) ? bar.moduleSlots : []
  readonly property bool effectActive: effectEnabled && barSupportsContentDim && !barHidden && shadeOpacity > 0
  readonly property bool dimSuppressed: barHovered || hoverGraceActive
  readonly property bool dimmed: effectActive && !dimSuppressed
  property real contentOpacity: dimmed ? 1 - shadeOpacity : 1

  property bool hoverGraceActive: false
  property var managedSlots: []

  function clamp(value, min, max) {
    if (!isFinite(value)) return min
    return Math.max(min, Math.min(max, value))
  }

  function syncHoverState() {
    hoverGraceTimer.stop()
    hoverGraceActive = effectActive && barHovered
  }

  function handleBarHoverChanged() {
    if (!effectActive) {
      syncHoverState()
    } else if (barHovered) {
      hoverGraceActive = true
      hoverGraceTimer.stop()
    } else if (hoverGraceActive) {
      hoverGraceTimer.restart()
    }
  }

  function setSlotOpacity(slot, value) {
    if (!slot || !("opacity" in slot)) return
    try {
      slot.opacity = value
    } catch (error) {
    }
  }

  function syncModuleOpacity() {
    var next = barModuleSlots || []
    var previous = managedSlots || []

    for (var i = 0; i < previous.length; i++) {
      if (next.indexOf(previous[i]) === -1) setSlotOpacity(previous[i], 1)
    }
    for (var j = 0; j < next.length; j++) setSlotOpacity(next[j], contentOpacity)

    managedSlots = next.slice()
  }

  function restoreModuleOpacity() {
    var slots = managedSlots || []
    for (var i = 0; i < slots.length; i++) setSlotOpacity(slots[i], 1)
    managedSlots = []
  }

  function currentSettings() {
    var config = shell && shell.shellConfig ? shell.shellConfig : null
    var plugins = config && Array.isArray(config.plugins) ? config.plugins : []
    for (var i = 0; i < plugins.length; i++) {
      var entry = plugins[i]
      if (entry && String(entry.id || "") === pluginId) return entry
    }
    return {}
  }

  function setting(name, fallback) {
    var value = pluginSettings ? pluginSettings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function saveSettings(nextValues) {
    if (!shell || typeof shell.updateEntryInline !== "function") return false

    var next = {}
    var current = pluginSettings || {}
    for (var key in current) {
      if (key !== "id") next[key] = current[key]
    }
    for (var nkey in nextValues) {
      if (nkey !== "id") next[nkey] = nextValues[nkey]
    }

    return shell.updateEntryInline(pluginId, next)
  }

  function setEffectEnabled(value) {
    saveSettings({ enabled: value === true })
    return value === true ? "enabled" : "disabled"
  }

  function setOpacity(rawValue) {
    var parsed = Number(rawValue)
    if (!isFinite(parsed)) return "invalid"

    var next = clamp(parsed, 0, 1)
    saveSettings({ opacity: next })
    return String(next)
  }

  function effectMode() {
    if (!effectEnabled || barHidden || shadeOpacity <= 0) return "off"
    if (!bar) return "waiting-for-bar"
    if (!barSupportsContentDim) return "unsupported-bar"
    return dimmed ? "content-dim" : "content-full"
  }

  function statusJson() {
    return JSON.stringify({
      enabled: effectEnabled,
      opacity: shadeOpacity,
      supported: barSupportsContentDim,
      barTransparent: barTransparent,
      barHidden: barHidden,
      barHovered: barHovered,
      mode: effectMode(),
      contentOpacity: contentOpacity,
      dimmed: dimmed,
      undimmed: !dimmed,
      hoverGraceActive: hoverGraceActive,
      overlay: false
    })
  }

  onBarChanged: {
    syncHoverState()
    syncModuleOpacity()
  }
  onBarModuleSlotsChanged: syncModuleOpacity()
  onBarHoveredChanged: handleBarHoverChanged()
  onEffectActiveChanged: syncHoverState()
  onContentOpacityChanged: syncModuleOpacity()
  Component.onCompleted: {
    syncHoverState()
    syncModuleOpacity()
  }
  Component.onDestruction: restoreModuleOpacity()

  Timer {
    id: hoverGraceTimer
    interval: 2500
    onTriggered: root.hoverGraceActive = false
  }

  IpcHandler {
    target: root.pluginId

    function status(): string {
      return root.statusJson()
    }

    function debug(): string {
      return root.statusJson()
    }

    function enable(): string {
      return root.setEffectEnabled(true)
    }

    function disable(): string {
      return root.setEffectEnabled(false)
    }

    function toggle(): string {
      return root.setEffectEnabled(!root.effectEnabled)
    }

    function opacity(value: string): string {
      return root.setOpacity(value)
    }
  }
}
