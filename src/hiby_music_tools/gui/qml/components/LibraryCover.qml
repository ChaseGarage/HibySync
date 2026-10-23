import QtQuick
import ".."

Rectangle {
    id: cover
    property string source: ""
    color: Theme.surface
    radius: Theme.radius
    clip: true
    Image {
        id: image
        anchors.fill: parent
        source: cover.source
        sourceSize.width: 240
        sourceSize.height: 240
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
    }
    Icon { anchors.centerIn: parent; width: Math.min(parent.width * 0.35, 44); height: width; visible: image.status !== Image.Ready; opacity: 0.6 }
}
