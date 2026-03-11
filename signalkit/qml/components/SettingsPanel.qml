import QtQuick

Flickable {
    id: panel
    contentHeight: innerCol.height
    clip: true

    property bool locked: false
    default property alias content: innerCol.children

    Column {
        id: innerCol
        anchors.left: parent.left; anchors.leftMargin: 16
        anchors.right: parent.right; anchors.rightMargin: 16
        width: parent.width - 32
        spacing: 4
        opacity: panel.locked ? 0.35 : 1.0
        Behavior on opacity { NumberAnimation { duration: 200 } }
    }

    // Lock overlay — blocks interaction when vehicle is moving
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        visible: panel.locked
        z: 100

        MouseArea {
            anchors.fill: parent
            onClicked: {}
        }

        Column {
            anchors.centerIn: parent
            spacing: 6
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Vehicle in motion"
                font.pixelSize: 13; font.weight: Font.Bold
                color: "#71717a"
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Stop to change settings"
                font.pixelSize: 10
                color: "#52525b"
            }
        }
    }
}
