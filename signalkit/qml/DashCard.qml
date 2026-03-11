import QtQuick
import QtQuick.Layouts

Rectangle {
    id: card
    radius: 8
    color: "#18181b"
    border.width: 1; border.color: "#27272a"

    property string label: ""
    property string value: "---"
    property string unit: ""
    property color accent: "#3b82f6"
    property color valueColor: "#e4e4e7"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 2

        Text {
            text: card.label.toUpperCase()
            font.pixelSize: 7
            font.weight: Font.Bold
            font.letterSpacing: 1.5
            color: Qt.rgba(card.accent.r, card.accent.g, card.accent.b, 0.5)
        }

        Text {
            text: card.value
            font.pixelSize: 28
            font.weight: Font.ExtraBold
            color: card.valueColor
            font.features: {"tnum": 1}
        }

        Text {
            text: card.unit
            font.pixelSize: 10
            font.weight: Font.Medium
            color: "#71717a"
            visible: card.unit !== ""
        }

        Item { Layout.fillHeight: true }
    }
}
