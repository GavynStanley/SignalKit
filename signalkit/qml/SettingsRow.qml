import QtQuick

Item {
    id: row
    width: parent ? parent.width : 200
    height: 36

    property string label: ""
    property string valueText: ""

    Rectangle {
        anchors.fill: parent
        color: "transparent"

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            text: row.label
            font.pixelSize: 11; font.weight: Font.Medium
            color: "#a1a1aa"
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            text: row.valueText
            font.pixelSize: 10; font.family: "Menlo"
            color: "#71717a"
        }
        Rectangle {
            width: parent.width; height: 1
            anchors.bottom: parent.bottom
            color: "#1c1c1e"
        }
    }
}
