import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "views"

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

    // -- View metadata for recent dock buttons --
    property var viewMeta: ({
        "dashboard": { icon: "bolt.svg",     label: "OBD",      color: root.accent },
        "settings":  { icon: "settings.svg", label: "Settings",  color: "#a1a1aa"   },
        "dev":       { icon: "terminal.svg", label: "Dev",       color: "#f59e0b"   }
    })

    // -- Recent views (last 2 non-home views visited, most recent first) --
    property var recentViews: []

    onCurrentViewChanged: {
        // Track recent views (skip home)
        if (currentView !== "home") {
            var updated = recentViews.filter(function(v) { return v !== currentView })
            updated.unshift(currentView)
            if (updated.length > 2) updated = updated.slice(0, 2)
            recentViews = updated
        }

        // Calculate slide direction for transitions
        var viewOrder = ["home", "dashboard", "settings", "dev"]
        var oldIdx = viewOrder.indexOf(previousView)
        var newIdx = viewOrder.indexOf(currentView)
        var goingForward = (currentView === "home") ? false : (previousView === "home") ? true : newIdx > oldIdx
        mainContent._slideDirection = goingForward ? 1 : -1
        previousView = currentView
    }

    // -- Sidebar Dock (CarPlay-style) --
    Rectangle {
        id: dock
        width: 72; height: parent.height
        color: "#111113"
        z: 10
        Rectangle { width: 1; height: parent.height; anchors.right: parent.right; color: "#27272a" }

        ColumnLayout {
            anchors.fill: parent
            anchors.topMargin: 12
            anchors.bottomMargin: 10
            spacing: 6

            // Home / app grid button (always present)
            DockButton {
                icon: "" + iconsPath + "home.svg"
                label: "Home"
                active: currentView === "home"
                onClicked: currentView = "home"
                iconColor: "#a1a1aa"
            }

            // Separator
            Rectangle {
                Layout.preferredWidth: 32; Layout.preferredHeight: 1
                Layout.alignment: Qt.AlignHCenter
                color: "#27272a"
                visible: root.recentViews.length > 0
            }

            // Recent view slots (up to 2)
            Repeater {
                model: root.recentViews.length

                DockButton {
                    required property int index
                    property string viewId: root.recentViews[index]
                    property var meta: root.viewMeta[viewId] || { icon: "bolt.svg", label: "?", color: "#a1a1aa" }
                    icon: "" + iconsPath + meta.icon
                    label: meta.label
                    active: root.currentView === viewId
                    iconColor: meta.color
                    onClicked: root.currentView = viewId
                }
            }

            Item { Layout.fillHeight: true }

            // Exit button
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 40; height: 40; radius: 12
                color: exitMa.containsMouse ? "#2a1215" : "transparent"
                Image {
                    anchors.centerIn: parent
                    source: "" + iconsPath + "power.svg"
                    sourceSize: Qt.size(18, 18)
                    smooth: true
                }
                MouseArea {
                    id: exitMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Qt.quit()
                }
            }
        }
    }

    // -- Top bar: view title left, status + clock right --
    property string viewTitle: {
        if (currentView === "dashboard") return "DASHBOARD"
        if (currentView === "settings") return "SETTINGS"
        if (currentView === "dev") return "DEV CONSOLE"
        return ""
    }

    Rectangle {
        id: topBar
        anchors.left: dock.right; anchors.right: parent.right; anchors.top: parent.top
        height: 36; color: "transparent"; z: 5
        Rectangle { width: parent.width; height: 1; anchors.bottom: parent.bottom; color: "#27272a" }

        // View title (left)
        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 16
            text: root.viewTitle
            font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 2
            color: "#71717a"
            visible: root.viewTitle !== ""
        }

        // Status + clock (right)
        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right; anchors.rightMargin: 16
            spacing: 8
            StatusDot {
                connected: bridge.obdConnected
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
                // font.features: {"tnum": 1}  // Qt 6.6+ only
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    // -- Transition config --
    property string previousView: "home"
    property int _transitionDuration: 250

    // -- Main content area --
    Item {
        id: mainContent
        anchors.left: dock.right
        anchors.right: parent.right
        anchors.top: topBar.bottom
        anchors.bottom: parent.bottom
        clip: true

        property int _slideDirection: 1  // 1 = slide from right, -1 = slide from left
        property real _slideOffset: 40   // pixels to slide

        HomeView {
            id: homeView
            width: parent.width; height: parent.height
            accent: root.accent
            onNavigate: (view) => root.currentView = view

            opacity: root.currentView === "home" ? 1 : 0
            transform: Translate { x: root.currentView === "home" ? 0 : mainContent._slideOffset * -mainContent._slideDirection }
            Behavior on opacity { NumberAnimation { duration: root._transitionDuration; easing.type: Easing.OutCubic } }

            visible: opacity > 0
        }

        DashboardView {
            id: dashView
            width: parent.width; height: parent.height
            accent: root.accent

            opacity: root.currentView === "dashboard" ? 1 : 0
            transform: Translate { x: root.currentView === "dashboard" ? 0 : mainContent._slideOffset * mainContent._slideDirection }
            Behavior on opacity { NumberAnimation { duration: root._transitionDuration; easing.type: Easing.OutCubic } }

            visible: opacity > 0
        }

        SettingsView {
            id: settingsView
            width: parent.width; height: parent.height
            accent: root.accent
            locked: bridge.vehicleMoving

            opacity: root.currentView === "settings" ? 1 : 0
            transform: Translate { x: root.currentView === "settings" ? 0 : mainContent._slideOffset * mainContent._slideDirection }
            Behavior on opacity { NumberAnimation { duration: root._transitionDuration; easing.type: Easing.OutCubic } }

            visible: opacity > 0
        }

        DevConsoleView {
            id: devView
            width: parent.width; height: parent.height
            accent: root.accent

            opacity: root.currentView === "dev" ? 1 : 0
            transform: Translate { x: root.currentView === "dev" ? 0 : mainContent._slideOffset * mainContent._slideDirection }
            Behavior on opacity { NumberAnimation { duration: root._transitionDuration; easing.type: Easing.OutCubic } }

            visible: opacity > 0
        }
    }
}
