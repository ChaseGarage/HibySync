import QtQuick
import ".."

Rectangle {
    id: artwork
    property string source: ""
    color: Theme.surface
    radius: Theme.radius
    clip: true
    Image {
        anchors.fill: parent
        source: artwork.source
        fillMode: Image.PreserveAspectCrop
        visible: status === Image.Ready
    }
    Icon {
        name: "music"
        anchors.centerIn: parent
        width: Math.min(parent.width * 0.4, 48)
        height: width
        visible: !artwork.source
        opacity: 0.6
    }
}
