import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.example.custom-clock"
  manageIpc: false

  SystemClock { id: clock; precision: SystemClock.Minutes }

  KeyboardPanel {
    id: panel
    Column {
      Text {
        text: Qt.formatDateTime(clock.date, "dddd, d MMMM yyyy")
        color: root.barForeground
      }
    }
  }
}
