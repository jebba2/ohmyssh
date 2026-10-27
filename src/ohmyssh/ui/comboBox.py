"""A combo box whose popup list is never narrower than the box itself."""

from PySide6.QtWidgets import QComboBox


class ComboBox(QComboBox):
    """QComboBox whose popup shows every choice in full.

    With the app stylesheet the macOS style still insets the popup rectangle as if the
    native frame were there, so the list comes up narrower than the box and elides its
    text. Giving the list the box's width when it opens keeps the choices readable.
    """

    def showPopup(self) -> None:
        """Open the popup list at least as wide as the box."""
        self.view().setMinimumWidth(self.width())
        super().showPopup()
