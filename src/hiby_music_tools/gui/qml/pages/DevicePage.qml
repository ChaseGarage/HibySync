import QtQuick
import QtQuick.Layouts

StackLayout {
    required property var manager
    required property var sourceController
    currentIndex: manager.sync.viewOpen ? 1 : 0
    DeviceDashboard { manager: parent.manager; sourceController: parent.sourceController }
    DeviceSyncPage { manager: parent.manager }
}
