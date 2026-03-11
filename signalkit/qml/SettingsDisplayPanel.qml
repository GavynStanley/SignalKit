import QtQuick
import QtQuick.Layouts

Flickable {
    id: displayPanel
    contentHeight: col.height
    clip: true

    property color accent: "#3b82f6"
    property string activeTheme: "blue"

    Column {
        id: col
        width: parent.width
        padding: 16
        spacing: 4

        SettingsSectionLabel { text: "THEME COLOR" }

        Row {
            spacing: 6
            Repeater {
                model: [
                    {"name": "red",    "color": "#DC2626"},
                    {"name": "blue",   "color": "#3b82f6"},
                    {"name": "green",  "color": "#22c55e"},
                    {"name": "purple", "color": "#a855f7"},
                    {"name": "orange", "color": "#f97316"},
                    {"name": "cyan",   "color": "#06b6d4"},
                    {"name": "pink",   "color": "#ec4899"}
                ]
                Rectangle {
                    required property var modelData
                    width: 28; height: 28; radius: 8
                    color: modelData.color
                    border.width: 2
                    border.color: activeTheme === modelData.name ? "#ffffff" : "transparent"

                    scale: swatchMA.pressed ? 0.88 : 1.0
                    Behavior on scale { NumberAnimation { duration: 100 } }

                    MouseArea {
                        id: swatchMA
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: activeTheme = parent.modelData.name
                    }
                }
            }
        }

        Item { width: 1; height: 8 }

        SettingsRow { label: "Speed"; valueText: "MPH" }
        SettingsRow { label: "Temperature"; valueText: "°C" }
        SettingsRow { label: "Clock"; valueText: "12hr" }
        SettingsRow { label: "Sparklines"; valueText: "On" }
    }
}
