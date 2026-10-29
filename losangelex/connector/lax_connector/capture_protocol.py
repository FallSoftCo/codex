"""Installed native capture protocols shared by dispatcher and owner checks."""
HOST_SCOPED_CAPTURE = "lax-automatic-native-capture/v3"
DELIVERY_CAPTURE = frozenset({"lax-automatic-native-capture/v2", HOST_SCOPED_CAPTURE})
SUPPORTED_CAPTURE = DELIVERY_CAPTURE | {"lax-automatic-native-capture/v1"}
