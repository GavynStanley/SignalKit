import QtQuick
import QtQuick.Layouts

Item {
    id: btn
    Layout.preferredWidth: 40
    Layout.preferredHeight: 52
    Layout.alignment: Qt.AlignHCenter

    property string icon: ""
    property string label: ""
    property bool active: false
    property color iconColor: "#a1a1aa"
    signal clicked()

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 3

        Rectangle {
            Layout.preferredWidth: 36; Layout.preferredHeight: 36
            Layout.alignment: Qt.AlignHCenter
            radius: 10
            color: btn.active ? Qt.rgba(btn.iconColor.r, btn.iconColor.g, btn.iconColor.b, 0.12) : "transparent"

            Image {
                anchors.centerIn: parent
                source: btn.icon
                sourceSize: Qt.size(20, 20)
                smooth: true
            }

            MouseArea {
                anchors.fill: parent
                onClicked: btn.clicked()
                cursorShape: Qt.PointingHandCursor
            }
        }

        Text {
            Layout.alignment: Qt.AlignHCenter
            text: btn.label
            font.pixelSize: 8
            font.weight: Font.DemiBold
            color: btn.active ? "#e4e4e7" : "#52525b"
        }
    }

    // Active indicator bar
    Rectangle {
        width: 3; height: 16; radius: 1.5
        anchors.left: parent.left; anchors.leftMargin: -2
        anchors.verticalCenter: parent.verticalCenter
        color: btn.iconColor
        visible: btn.active
    }
}
