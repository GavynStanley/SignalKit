import QtQuick
import QtQuick.Layouts

Item {
    id: dashRoot
    property color accent: "#3b82f6"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Status bar
        Rectangle {
            Layout.fillWidth: true; Layout.preferredHeight: 26
            color: "#18181b"
            Rectangle { width: parent.width; height: 1; anchors.bottom: parent.bottom; color: "#27272a" }

            RowLayout {
                anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                spacing: 6
                Rectangle { width: 7; height: 7; radius: 3.5; color: "#22c55e" }
                Text { text: "Connected — Demo Mode"; font.pixelSize: 11; color: "#71717a" }
                Item { Layout.fillWidth: true }
                Text { text: "0:42"; font.pixelSize: 10; color: "#52525b"; font.features: {"tnum": 1} }
                Text { text: "12.3 mi"; font.pixelSize: 10; color: "#52525b"; font.features: {"tnum": 1} }
                Rectangle { width: 1; height: 12; color: "#3f3f46" }
                Text { text: bridge.clockText; font.pixelSize: 11; color: "#52525b"; font.features: {"tnum": 1} }
            }
        }

        // Dashboard grid
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.margins: 4

            GridLayout {
                anchors.fill: parent
                columns: 2; rows: 4
                columnSpacing: 4; rowSpacing: 4

                // RPM
                DashCard {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Layout.rowSpan: 1
                    Layout.columnSpan: 1
                    label: "RPM"
                    value: "3,247"
                    accent: dashRoot.accent

                    // RPM bar
                    Rectangle {
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: 8
                        height: 4; radius: 2
                        color: "#27272a"
                        Rectangle {
                            width: parent.width * 0.45; height: parent.height; radius: 2
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: dashRoot.accent }
                                GradientStop { position: 1; color: Qt.lighter(dashRoot.accent, 1.3) }
                            }
                        }
                    }
                }

                // Speed
                DashCard {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    label: "Speed"
                    value: "47"
                    unit: "MPH"
                    accent: dashRoot.accent
                }

                // Coolant
                DashCard {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    label: "Coolant"
                    value: "92"
                    unit: "°C"
                    accent: dashRoot.accent
                }

                // Battery
                DashCard {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    label: "Battery"
                    value: "14.2"
                    unit: "V"
                    accent: dashRoot.accent
                    valueColor: "#22c55e"
                }

                // Throttle
                DashCard {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    label: "Throttle"
                    value: "23"
                    unit: "%"
                    accent: dashRoot.accent
                }

                // Engine Load
                DashCard {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    label: "Engine Load"
                    value: "31"
                    unit: "%"
                    accent: dashRoot.accent
                }

                // DTC row
                Rectangle {
                    Layout.fillWidth: true; Layout.columnSpan: 2
                    Layout.preferredHeight: 28
                    radius: 8; color: "#18181b"; border.width: 1; border.color: "#27272a"
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10
                        spacing: 8
                        Text {
                            text: "FAULT CODES"
                            font.pixelSize: 8; font.weight: Font.Bold; font.letterSpacing: 1.5
                            color: "#52525b"
                        }
                        Text {
                            text: "No active fault codes"
                            font.pixelSize: 10; color: "#22c55e"
                        }
                    }
                }
            }
        }
    }
}
