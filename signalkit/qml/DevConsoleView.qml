import QtQuick
import QtQuick.Layouts

Item {
    id: devRoot
    property color accent: "#3b82f6"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Header
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 36
            color: "transparent"
            Rectangle { width: parent.width; height: 1; anchors.bottom: parent.bottom; color: "#27272a" }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left; anchors.leftMargin: 16
                text: "DEV CONSOLE"
                font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 2
                color: "#71717a"
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                anchors.right: parent.right; anchors.rightMargin: 16
                text: "Clear"
                font.pixelSize: 10; color: "#52525b"
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: terminalModel.clear()
                }
            }
        }

        // Quick commands
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 38
            color: "transparent"
            Rectangle { width: parent.width; height: 1; anchors.bottom: parent.bottom; color: "#27272a" }

            Row {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left; anchors.leftMargin: 12
                spacing: 5
                Repeater {
                    model: ["ATZ", "ATI", "ATRV", "0100", "0105", "010C", "010D", "03"]
                    Rectangle {
                        required property string modelData
                        width: cmdText.width + 16; height: 24; radius: 8
                        color: "#18181b"; border.width: 1; border.color: "#27272a"
                        Text {
                            id: cmdText; anchors.centerIn: parent
                            text: modelData
                            font.pixelSize: 10; font.weight: Font.DemiBold; font.family: "Menlo"
                            color: "#a1a1aa"
                        }
                        MouseArea {
                            anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                terminalModel.append({"text": "> " + modelData, "type": "cmd"})
                                terminalModel.append({"text": "41 0C 0C 8A", "type": "resp"})
                            }
                        }
                    }
                }
            }
        }

        // Terminal output
        ListView {
            id: terminalView
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.margins: 8
            clip: true
            spacing: 2

            model: ListModel {
                id: terminalModel
                ListElement { text: "SignalKit Dev Console ready."; type: "info" }
                ListElement { text: "> ATZ"; type: "cmd" }
                ListElement { text: "ELM327 v1.5"; type: "resp" }
                ListElement { text: "> ATRV"; type: "cmd" }
                ListElement { text: "14.2V"; type: "resp" }
            }

            delegate: Text {
                required property string text
                required property string type
                width: terminalView.width
                text: this.text
                font.pixelSize: 11; font.family: "Menlo"
                wrapMode: Text.WrapAnywhere
                color: type === "cmd" ? "#3b82f6" : type === "resp" ? "#22c55e" : type === "err" ? "#ef4444" : "#71717a"
            }

            onCountChanged: positionViewAtEnd()
        }

        // Input bar
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 34
            color: "#111113"
            Rectangle { width: parent.width; height: 1; anchors.top: parent.top; color: "#27272a" }

            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 8
                spacing: 8
                Text { text: ">"; font.pixelSize: 14; font.weight: Font.Bold; font.family: "Menlo"; color: devRoot.accent }
                Rectangle {
                    Layout.fillWidth: true; Layout.preferredHeight: 24
                    radius: 6; color: "#18181b"; border.width: 1; border.color: "#27272a"
                    TextInput {
                        id: devInput
                        anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8
                        verticalAlignment: TextInput.AlignVCenter
                        font.pixelSize: 11; font.family: "Menlo"
                        color: "#d4d4d8"
                        onAccepted: {
                            if (text.trim() !== "") {
                                terminalModel.append({"text": "> " + text, "type": "cmd"})
                                terminalModel.append({"text": "(demo mode — no response)", "type": "info"})
                                text = ""
                            }
                        }
                    }
                }
                Rectangle {
                    width: 50; height: 24; radius: 6
                    color: devRoot.accent
                    Text { anchors.centerIn: parent; text: "Send"; font.pixelSize: 10; font.weight: Font.Bold; color: "#fff" }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: devInput.accepted()
                    }
                }
            }
        }
    }
}
