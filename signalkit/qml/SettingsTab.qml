import QtQuick

Item {
    id: tab
    width: parent ? parent.width : 140
    height: 38

    property string label: ""
    property string icon: ""
    property string tabId: ""
    property bool active: false
    property color accent: "#3b82f6"
    signal clicked()

    Rectangle {
        anchors.fill: parent
        color: tab.active ? Qt.rgba(tab.accent.r, tab.accent.g, tab.accent.b, 0.08) : (tabMA.containsMouse ? "#1c1c1e" : "transparent")

        // Active indicator
        Rectangle {
            width: 2; height: parent.height
            anchors.left: parent.left
            color: tab.accent
            visible: tab.active
        }

        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 14
            spacing: 8

            Text {
                text: tab.icon
                font.pixelSize: 12
                color: tab.active ? "#e4e4e7" : "#71717a"
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: tab.label
                font.pixelSize: 11
                font.weight: Font.DemiBold
                color: tab.active ? "#e4e4e7" : "#71717a"
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        MouseArea {
            id: tabMA
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tab.clicked()
        }
    }
}
