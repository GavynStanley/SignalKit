import QtQuick
import QtQuick.Layouts
import QtQuick.Controls

Item {
    id: settingsRoot
    property color accent: "#3b82f6"
    property string activeTab: "display"

    // Header
    Rectangle {
        id: settingsHeader
        width: parent.width; height: 36
        color: "transparent"
        Rectangle { width: parent.width; height: 1; anchors.bottom: parent.bottom; color: "#27272a" }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 16
            text: "SETTINGS"
            font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 2
            color: "#71717a"
        }
    }

    Row {
        anchors.top: settingsHeader.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right

        // Sidebar
        Rectangle {
            id: sidebar
            width: 140; height: parent.height
            color: "#111113"
            Rectangle { width: 1; height: parent.height; anchors.right: parent.right; color: "#27272a" }

            Column {
                anchors.fill: parent
                anchors.topMargin: 8

                SettingsTab { label: "Display";    icon: "☀";  tabId: "display";   active: activeTab === "display";   accent: settingsRoot.accent; onClicked: activeTab = "display" }
                SettingsTab { label: "Bluetooth";  icon: "⌁";  tabId: "bluetooth"; active: activeTab === "bluetooth"; accent: settingsRoot.accent; onClicked: activeTab = "bluetooth" }
                SettingsTab { label: "Warnings";   icon: "⚠";  tabId: "warnings";  active: activeTab === "warnings";  accent: settingsRoot.accent; onClicked: activeTab = "warnings" }
                SettingsTab { label: "Network";    icon: "◉";  tabId: "network";   active: activeTab === "network";   accent: settingsRoot.accent; onClicked: activeTab = "network" }
                SettingsTab { label: "Advanced";   icon: "<>";  tabId: "advanced";  active: activeTab === "advanced";  accent: settingsRoot.accent; onClicked: activeTab = "advanced" }

                Item { width: 1; height: parent.height - 5 * 38 - 46 }

                Rectangle { width: parent.width - 16; height: 1; color: "#1c1c1e"; anchors.horizontalCenter: parent.horizontalCenter }
                SettingsTab { label: "About";      icon: "ⓘ";  tabId: "about";     active: activeTab === "about";     accent: settingsRoot.accent; onClicked: activeTab = "about" }
            }
        }

        // Content
        Item {
            width: parent.width - sidebar.width; height: parent.height
            clip: true

            // Display panel
            SettingsDisplayPanel {
                anchors.fill: parent
                visible: activeTab === "display"
                accent: settingsRoot.accent
            }

            // Bluetooth panel
            Flickable {
                anchors.fill: parent; visible: activeTab === "bluetooth"
                contentHeight: btCol.height; clip: true
                Column {
                    id: btCol; width: parent.width; padding: 16; spacing: 4
                    SettingsSectionLabel { text: "OBD ADAPTER" }
                    SettingsRow { label: "MAC Address"; valueText: "AA:BB:CC:DD:EE:FF" }
                    SettingsRow { label: "RFCOMM Channel"; valueText: "1" }
                    SettingsSectionLabel { text: "PHONE"; topMargin: 14 }
                    SettingsRow { label: "Phone Bluetooth"; valueText: "Not set" }
                    SettingsRow { label: "Auto-Connect"; valueText: "Off" }
                }
            }

            // Warnings panel
            Flickable {
                anchors.fill: parent; visible: activeTab === "warnings"
                contentHeight: warnCol.height; clip: true
                Column {
                    id: warnCol; width: parent.width; padding: 16; spacing: 4
                    SettingsRow { label: "RPM Redline"; valueText: "6500" }
                    SettingsRow { label: "Overheat °C"; valueText: "105" }
                    SettingsRow { label: "Low Battery V"; valueText: "12.0" }
                    SettingsRow { label: "Critical Battery V"; valueText: "11.0" }
                }
            }

            // Network panel
            Flickable {
                anchors.fill: parent; visible: activeTab === "network"
                contentHeight: netCol.height; clip: true
                Column {
                    id: netCol; width: parent.width; padding: 16; spacing: 4
                    SettingsSectionLabel { text: "WIFI HOTSPOT" }
                    SettingsRow { label: "SSID"; valueText: "SignalKit" }
                    SettingsRow { label: "Password"; valueText: "••••••••" }
                }
            }

            // Advanced panel
            Flickable {
                anchors.fill: parent; visible: activeTab === "advanced"
                contentHeight: advCol.height; clip: true
                Column {
                    id: advCol; width: parent.width; padding: 16; spacing: 4
                    SettingsRow { label: "Fast Poll (sec)"; valueText: "1.0" }
                    SettingsRow { label: "Slow Poll (sec)"; valueText: "10" }
                    SettingsRow { label: "Scan PIDs on Boot"; valueText: "On" }
                }
            }

            // About panel
            Item {
                anchors.fill: parent; visible: activeTab === "about"
                Column {
                    anchors.centerIn: parent; spacing: 6
                    width: 280

                    // Logo
                    Rectangle {
                        width: 52; height: 52; radius: 14
                        anchors.horizontalCenter: parent.horizontalCenter
                        color: Qt.rgba(settingsRoot.accent.r, settingsRoot.accent.g, settingsRoot.accent.b, 0.12)
                        border.width: 1; border.color: Qt.rgba(settingsRoot.accent.r, settingsRoot.accent.g, settingsRoot.accent.b, 0.25)
                        Text {
                            anchors.centerIn: parent; text: "⚡"
                            font.pixelSize: 24
                        }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "SignalKit"; font.pixelSize: 16; font.weight: Font.ExtraBold; color: "#e4e4e7"
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "v0.1.0 (abc1234)"; font.pixelSize: 10; color: "#52525b"
                    }

                    Item { width: 1; height: 12 }

                    SettingsRow { label: "IP Address"; valueText: "192.168.4.1"; width: parent.width }
                    SettingsRow { label: "Web Port"; valueText: "8080"; width: parent.width }
                    SettingsRow { label: "OBD Adapter"; valueText: "AA:BB:CC:DD:EE:FF"; width: parent.width }
                    SettingsRow { label: "Theme"; valueText: "Blue"; width: parent.width }

                    Item { width: 1; height: 8 }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Open-source OBD2 dashboard for Raspberry Pi."
                        font.pixelSize: 9; color: "#3f3f46"
                    }
                }
            }
        }
    }
}
