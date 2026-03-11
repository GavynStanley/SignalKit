import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects

ApplicationWindow {
    id: root
    visible: true
    width: 800; height: 480
    title: "SignalKit"
    color: "#0a0a0a"
    flags: Qt.FramelessWindowHint | Qt.Window
    minimumWidth: 800; minimumHeight: 480
    maximumWidth: 800; maximumHeight: 480

    // -- Theme properties --
    property color accent: bridge.accent
    property color accentDim: Qt.rgba(accent.r, accent.g, accent.b, 0.15)
    property string currentView: "home"

    // -- Sidebar Dock --
    Rectangle {
        id: dock
        width: 56; height: parent.height
        color: "#111113"
        z: 10
        Rectangle { width: 1; height: parent.height; anchors.right: parent.right; color: "#27272a" }

        ColumnLayout {
            anchors.fill: parent
            anchors.topMargin: 12
            anchors.bottomMargin: 8
            spacing: 4

            DockButton {
                icon: "" + iconsPath + "home.svg"
                label: "Home"
                active: currentView === "home"
                onClicked: currentView = "home"
                iconColor: "#a1a1aa"
            }
            DockButton {
                icon: "" + iconsPath + "bolt.svg"
                label: "OBD"
                active: currentView === "dashboard"
                onClicked: currentView = "dashboard"
                iconColor: root.accent
            }
            DockButton {
                icon: "" + iconsPath + "settings.svg"
                label: "Settings"
                active: currentView === "settings"
                onClicked: currentView = "settings"
                iconColor: "#a1a1aa"
            }
            DockButton {
                icon: "" + iconsPath + "terminal.svg"
                label: "Dev"
                active: currentView === "dev"
                onClicked: currentView = "dev"
                iconColor: "#a1a1aa"
            }

            Item { Layout.fillHeight: true }

            // Exit button
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 32; height: 32; radius: 8
                color: exitMa.containsMouse ? "#2a1215" : "transparent"
                Image {
                    anchors.centerIn: parent
                    source: "" + iconsPath + "power.svg"
                    sourceSize: Qt.size(16, 16)
                    smooth: true
                }
                MouseArea {
                    id: exitMa
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: Qt.quit()
                }
            }
        }
    }

    // -- Top status bar (matches settings/dev header style) --
    Rectangle {
        id: topBar
        anchors.left: dock.right; anchors.right: parent.right; anchors.top: parent.top
        height: 36; color: "transparent"; z: 5
        Rectangle { width: parent.width; height: 1; anchors.bottom: parent.bottom; color: "#27272a" }

        Row {
            anchors.centerIn: parent
            spacing: 8
            Rectangle {
                width: 6; height: 6; radius: 3
                color: bridge.obdConnected ? "#22c55e" : "#ef4444"
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: bridge.obdConnected ? "Connected" : "Disconnected"
                font.pixelSize: 10; color: "#52525b"
                anchors.verticalCenter: parent.verticalCenter
            }
            Text { text: "|"; font.pixelSize: 10; color: "#27272a"; anchors.verticalCenter: parent.verticalCenter }
            Text {
                text: bridge.clockText
                font.pixelSize: 10; color: "#52525b"
                font.features: {"tnum": 1}
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    // -- Main content area --
    Item {
        id: mainContent
        anchors.left: dock.right
        anchors.right: parent.right
        anchors.top: topBar.bottom
        anchors.bottom: parent.bottom
        clip: true

        HomeView {
            id: homeView
            anchors.fill: parent
            visible: currentView === "home"
            accent: root.accent
            onNavigate: (view) => currentView = view
        }

        DashboardView {
            id: dashView
            anchors.fill: parent
            visible: currentView === "dashboard"
            accent: root.accent
        }

        SettingsView {
            id: settingsView
            anchors.fill: parent
            visible: currentView === "settings"
            accent: root.accent
        }

        DevConsoleView {
            id: devView
            anchors.fill: parent
            visible: currentView === "dev"
            accent: root.accent
        }
    }
}
