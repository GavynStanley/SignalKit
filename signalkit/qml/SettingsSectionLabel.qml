import QtQuick

Item {
    width: parent ? parent.width : 200
    height: 24 + topMargin

    property string text: ""
    property int topMargin: 0

    Text {
        anchors.bottom: parent.bottom; anchors.bottomMargin: 4
        anchors.left: parent.left
        text: parent.text
        font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.2
        color: "#52525b"
    }
}
