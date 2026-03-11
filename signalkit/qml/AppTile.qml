import QtQuick
import QtQuick.Layouts

Item {
    id: tile
    width: 76; height: 82

    property string label: ""
    property color gradStart: "#1c1c1e"
    property color gradEnd: "#2a2a2e"
    property color borderColor: "#3f3f46"
    property color iconColor: "#a1a1aa"
    property string iconSource: ""
    signal clicked()

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 8

        Rectangle {
            id: iconRect
            width: 60; height: 60; radius: 14
            border.width: 1; border.color: tile.borderColor

            gradient: Gradient {
                GradientStop { position: 0.0; color: tile.gradStart }
                GradientStop { position: 1.0; color: tile.gradEnd }
            }

            Image {
                anchors.centerIn: parent
                source: tile.iconSource
                sourceSize: Qt.size(24, 24)
                smooth: true
            }

            scale: tileMA.pressed ? 0.9 : tileMA.containsMouse ? 1.06 : 1.0
            Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }

            MouseArea {
                id: tileMA
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: tile.clicked()
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: tile.label
            font.pixelSize: 10
            font.weight: Font.DemiBold
            color: "#a1a1aa"
        }
    }
}
