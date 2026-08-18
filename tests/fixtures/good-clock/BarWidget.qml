import QtQuick
import Quickshell
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.example.custom-clock"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  SystemClock {
    id: clock
    precision: SystemClock.Minutes
  }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: Qt.formatTime(clock.date, "HH:mm")
    tooltipText: "Open Custom Clock"
  }
}
